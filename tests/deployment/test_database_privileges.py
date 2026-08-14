"""The runtime connects as a role that cannot change the database.

WHAT THIS PROTECTS
The application used to connect as the database owner: a superuser, owner of
every table and sequence, carrying BYPASSRLS. It performs no DDL — no
create_all, no DDL(), and the only raw statement it runs is SELECT 1 in the
health check — so none of that was ever needed. A logic flaw or injection in
one query had the whole cluster behind it.

These tests assert the separation from BOTH sides, because either alone is
satisfiable by a mistake:

  * the runtime role is not privileged, owns nothing, and cannot do DDL
  * the runtime role can still do every kind of DML the application performs,
    including nextval on the sequences every INSERT depends on
  * objects a FUTURE migration creates will be usable by the runtime role

That last one is the failure this file exists for. GRANT ... ON ALL TABLES
applies only to the tables that exist when it runs, so without default
privileges the next Alembic revision produces a table the application cannot
read — at runtime, in production, after a deploy that looked clean.

These run against the database the test suite is pointed at. Where the
restricted role does not exist — a developer who has not run
scripts/create_app_role.sh — they skip rather than fail, because they describe
a deployment property, not a property of the code.
"""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import TEST_DATABASE_URL

RUNTIME_ROLE = "helpdoctor_app"


def _url_role(url: str) -> str:
    from urllib.parse import urlsplit, unquote

    return unquote(urlsplit(url).username or "")


#: The suite runs against the restricted role once the harness is split. Where
#: it does not, these assertions have nothing to describe.
RESTRICTED = _url_role(TEST_DATABASE_URL) == RUNTIME_ROLE

restricted_only = pytest.mark.skipif(
    not RESTRICTED,
    reason=(
        "the test session is not using the restricted role; run "
        "scripts/create_app_role.sh and set TEST_DATABASE_URL to it"
    ),
)


@pytest.fixture
async def runtime_conn(setup_database):
    """A connection of its own, outside the suite's rollback fixture.

    The `db` fixture runs inside a transaction that is rolled back, which is
    exactly wrong for asserting what a role may do: a DDL attempt that fails
    poisons that transaction for every later statement in the test.

    Depends on setup_database even though it does not use the schema it builds.
    reset_database() drops the schema — which takes the grants and the default
    privileges with it, since those are recorded against the schema's OID — and
    then re-grants. Without this dependency these tests pass or fail on
    whatever the previous run happened to leave behind, which is how they first
    failed in isolation and passed in a larger selection.
    """

    engine = create_async_engine(TEST_DATABASE_URL, poolclass=None)

    async with engine.connect() as conn:
        yield conn

    await engine.dispose()


# ---------------------------------------------------------------------------
# What the runtime role must NOT be
# ---------------------------------------------------------------------------


@restricted_only
@pytest.mark.asyncio
async def test_the_runtime_role_is_not_a_superuser(runtime_conn):
    is_super = await runtime_conn.scalar(
        text("select rolsuper from pg_roles where rolname = current_user")
    )

    assert is_super is False


@restricted_only
@pytest.mark.asyncio
async def test_the_runtime_role_cannot_bypass_row_level_security(runtime_conn):
    """Stated now, while no policy exists. A role that silently bypasses RLS
    would make any policy adopted later decorative, and that is not a failure
    anything else would report."""

    bypasses = await runtime_conn.scalar(
        text("select rolbypassrls from pg_roles where rolname = current_user")
    )

    assert bypasses is False


@restricted_only
@pytest.mark.asyncio
async def test_the_runtime_role_has_no_administrative_attributes(runtime_conn):
    row = await runtime_conn.execute(
        text(
            "select rolcreatedb, rolcreaterole, rolreplication "
            "from pg_roles where rolname = current_user"
        )
    )
    createdb, createrole, replication = row.one()

    assert createdb is False
    assert createrole is False
    assert replication is False


@restricted_only
@pytest.mark.asyncio
async def test_the_runtime_role_owns_no_application_objects(runtime_conn):
    """Owners bypass their own tables' policies and can always ALTER them, so
    'not a superuser' is not sufficient on its own."""

    tables = await runtime_conn.scalar(
        text(
            "select count(*) from pg_tables "
            "where schemaname = 'public' and tableowner = current_user"
        )
    )
    sequences = await runtime_conn.scalar(
        text(
            "select count(*) from pg_sequences "
            "where schemaname = 'public' and sequenceowner = current_user"
        )
    )

    assert tables == 0
    assert sequences == 0


@restricted_only
@pytest.mark.asyncio
async def test_the_runtime_role_cannot_create_a_table(runtime_conn):
    with pytest.raises(Exception) as denied:
        await runtime_conn.execute(text("create table privilege_probe (id int)"))

    assert "permission denied" in str(denied.value).lower()


@restricted_only
@pytest.mark.asyncio
async def test_the_runtime_role_cannot_drop_an_application_table(runtime_conn):
    with pytest.raises(Exception) as denied:
        await runtime_conn.execute(text("drop table clinics"))

    assert "must be owner" in str(denied.value).lower() or (
        "permission denied" in str(denied.value).lower()
    )


@restricted_only
@pytest.mark.asyncio
async def test_the_runtime_role_cannot_alter_an_application_table(runtime_conn):
    with pytest.raises(Exception) as denied:
        await runtime_conn.execute(
            text("alter table clinics add column privilege_probe int")
        )

    assert "must be owner" in str(denied.value).lower() or (
        "permission denied" in str(denied.value).lower()
    )


# ---------------------------------------------------------------------------
# What the runtime role must still be able to do
# ---------------------------------------------------------------------------


@restricted_only
@pytest.mark.asyncio
async def test_the_runtime_role_can_perform_every_dml_verb(runtime_conn):
    """SELECT/INSERT/UPDATE/DELETE against a real application table, rolled
    back. Asserting the grant rows exist would not prove the role can use
    them — a missing sequence grant fails at INSERT, not at GRANT."""

    trans = await runtime_conn.begin()

    try:
        await runtime_conn.execute(text("select count(*) from clinics"))

        clinic_id = await runtime_conn.scalar(
            text(
                "insert into clinics (name, status) "
                "values ('privilege probe', 'ACTIVE') returning id"
            )
        )
        assert clinic_id is not None, "INSERT returned no id — sequence grant?"

        await runtime_conn.execute(
            text("update clinics set name = 'probe renamed' where id = :i"),
            {"i": clinic_id},
        )
        await runtime_conn.execute(
            text("delete from clinics where id = :i"), {"i": clinic_id}
        )
    finally:
        await trans.rollback()


@restricted_only
@pytest.mark.asyncio
async def test_the_runtime_role_can_use_every_sequence(runtime_conn):
    """Every primary key uses a nextval default — there are no identity
    columns — so a sequence missing its grant breaks INSERT on exactly one
    table, which is the kind of gap a single happy-path test would miss."""

    # The transaction is opened before the first statement: a connection
    # autobegins on its first execute, and calling begin() after that raises.
    trans = await runtime_conn.begin()

    try:
        sequences = (
            await runtime_conn.scalars(
                text(
                    "select sequencename from pg_sequences "
                    "where schemaname = 'public'"
                )
            )
        ).all()

        assert sequences, "no sequences found; the schema is not what this expects"

        for name in sequences:
            await runtime_conn.execute(
                text("select nextval(:s)"), {"s": f"public.{name}"}
            )
    finally:
        await trans.rollback()


# ---------------------------------------------------------------------------
# Future migrations
# ---------------------------------------------------------------------------


@restricted_only
@pytest.mark.asyncio
async def test_default_privileges_cover_objects_a_migration_will_create(
    runtime_conn,
):
    """THE ONE THAT IS EASY TO FORGET.

    Read from pg_default_acl rather than by creating a table, because creating
    one requires the privileged role and this connection is deliberately not
    it. The grants must be attached to the role that RUNS migrations — default
    privileges follow the creating role, not whoever ran the grant script.
    """

    rows = (
        await runtime_conn.execute(
            text(
                "select pg_get_userbyid(defaclrole), defaclobjtype::text, "
                "       defaclacl::text "
                "from pg_default_acl"
            )
        )
    ).all()

    by_type = {objtype: (owner, acl) for owner, objtype, acl in rows}

    assert "r" in by_type, (
        "no default privileges for TABLES: the next migration's table will be "
        "unreadable by the application"
    )
    assert "S" in by_type, "no default privileges for SEQUENCES"

    table_owner, table_acl = by_type["r"]
    assert table_owner == "helpdoctor_user", (
        f"default privileges are attached to {table_owner!r}, but migrations "
        "run as helpdoctor_user, so they will not apply"
    )

    # arwd = INSERT, SELECT, UPDATE, DELETE
    assert f"{RUNTIME_ROLE}=arwd" in table_acl, table_acl

    sequence_owner, sequence_acl = by_type["S"]
    assert sequence_owner == "helpdoctor_user"
    assert f"{RUNTIME_ROLE}=U" in sequence_acl, sequence_acl

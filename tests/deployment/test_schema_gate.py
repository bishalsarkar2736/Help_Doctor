"""Nothing serves traffic against a database this code does not expect.

THE GAP
Staging had a schema gate; production had none. Production's only protection was
that `migrate` ran `alembic upgrade head` and the app services waited for it to
exit 0 — which proves migrations were ATTEMPTED, not that the database ended up
where the code expects. A stack that keeps running never re-runs the one-shot
`migrate` at all, which is how staging sat eight days behind while every
container reported healthy.

THE SHAPE OF THE FIX
The check moved into the image as scripts/verify_schema.py, and the `migrate`
service now runs it after upgrading:

    command: sh -c 'alembic upgrade head && python -m scripts.verify_schema'

api, celery_worker, celery_beat and outbox_worker already declare
`depends_on: migrate: { condition: service_completed_successfully }`, so a
non-zero exit from either half stops the entire application from starting. The
gate needed no deployment script and no new framework — it borrows an ordering
guarantee that was already there, and it applies to production and staging
identically because both use the same service.

WHAT THESE TESTS DO NOT TOUCH
Any real database other than the test one. The revision checks below run against
the session's test database via the application engine, and the two "wrong
revision" cases are exercised by stubbing the reader rather than by writing to
alembic_version, so no test can leave a database stamped at the wrong revision.
"""

import ast
import pathlib
import re
from unittest.mock import AsyncMock, patch

import pytest

from scripts import verify_schema

yaml = pytest.importorskip("yaml")

REPO = pathlib.Path(__file__).parent.parent.parent
COMPOSE = REPO / "docker-compose.yml"
COMPOSE_STAGING = REPO / "docker-compose.staging.yml"
STAGING_SH = REPO / "scripts" / "staging.sh"

GATED_SERVICES = ("api", "celery_worker", "celery_beat", "outbox_worker")


class _Loader(yaml.SafeLoader):
    """SafeLoader tolerating compose's `!override` tag."""


_Loader.add_multi_constructor(
    "!",
    lambda loader, suffix, node: (
        loader.construct_sequence(node)
        if isinstance(node, yaml.SequenceNode)
        else loader.construct_mapping(node)
        if isinstance(node, yaml.MappingNode)
        else loader.construct_scalar(node)
    ),
)


@pytest.fixture(scope="module")
def base() -> dict:
    return yaml.load(COMPOSE.read_text(), Loader=_Loader)["services"]


def _migrate_command(services: dict) -> str:
    command = services["migrate"]["command"]

    return " ".join(command) if isinstance(command, list) else str(command)


# ---------------------------------------------------------------------------
# The gate runs, and runs after the upgrade
# ---------------------------------------------------------------------------


def test_the_migrate_service_verifies_after_upgrading(base):
    command = _migrate_command(base)

    assert "alembic upgrade head" in command
    assert "scripts.verify_schema" in command


def test_verification_is_conditional_on_the_upgrade_succeeding(base):
    """`&&`, not `;`. A failed upgrade must not be followed by a check that
    could pass against the old schema and mask it."""
    command = _migrate_command(base)

    upgrade = command.index("alembic upgrade head")
    verify = command.index("scripts.verify_schema")

    assert upgrade < verify, "the verification runs before the upgrade"
    assert "&&" in command[upgrade:verify], (
        "the two steps are not chained with && — a failed upgrade would still "
        "be followed by the check"
    )


@pytest.mark.parametrize("service", GATED_SERVICES)
def test_every_application_service_waits_for_the_gate(base, service):
    """The mechanism that turns a non-zero exit into "nothing starts"."""
    condition = base[service]["depends_on"]["migrate"]["condition"]

    assert condition == "service_completed_successfully"


def test_production_and_staging_share_one_migrate_service():
    """Staging overrides only the container name and env file, so it inherits
    the gate rather than carrying a second copy of it."""
    staging = yaml.load(COMPOSE_STAGING.read_text(), Loader=_Loader)["services"]

    assert set(staging["migrate"]) <= {"container_name", "env_file", "ports"}
    assert "command" not in staging["migrate"]


# ---------------------------------------------------------------------------
# One implementation
# ---------------------------------------------------------------------------


def test_staging_does_not_carry_its_own_copy_of_the_check():
    """The logic used to be inline shell in staging.sh. Two copies of a gate is
    how one of them silently stops matching the other."""
    script = STAGING_SH.read_text()

    for inlined in ("alembic current", "alembic heads", "alembic check"):
        assert inlined not in script, (
            f"staging.sh still runs {inlined!r} itself instead of delegating"
        )

    assert "scripts.verify_schema" in script


def test_the_verifier_takes_no_database_argument():
    """It cannot be pointed at a database.

    There is no host, port or URL parameter anywhere in the module: the revision
    is read through the application engine, and the drift check goes through
    alembic/env.py. Both resolve their target from the settings of whichever
    container the process runs in, so aiming this at production requires being
    in a production container — the only case where that is correct.
    """
    tree = ast.parse(pathlib.Path(verify_schema.__file__).read_text())

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = {a.arg for a in node.args.args + node.args.kwonlyargs}

            assert not (names & {"url", "dsn", "host", "database", "database_url"}), (
                f"{node.name} accepts a database target"
            )

    source = pathlib.Path(verify_schema.__file__).read_text()

    assert "argparse" not in source
    assert "sys.argv" not in source


# ---------------------------------------------------------------------------
# What the verifier decides
# ---------------------------------------------------------------------------


def test_it_passes_when_the_database_is_at_head():
    """Run for real against the session's test database, which conftest builds
    by migrating to head — so this is the "already at head, idempotent" case."""
    assert verify_schema.verify() == 0


def test_the_code_head_is_a_real_revision():
    head = verify_schema.code_head()

    assert head and re.fullmatch(r"[0-9a-f]{12}", head)


@pytest.mark.asyncio
async def test_it_reads_the_revision_from_the_database():
    revision = await verify_schema.database_revision()

    assert revision == verify_schema.code_head()


def test_it_fails_when_the_database_is_behind():
    """Stubbed rather than written: rewinding alembic_version for real would
    leave the test database stamped wrongly if the test failed midway."""
    with patch.object(
        verify_schema,
        "_revision_and_dispose",
        new=AsyncMock(return_value="000000000000"),
    ):
        assert verify_schema.verify() == 1


def test_it_fails_when_the_database_was_never_stamped():
    with patch.object(
        verify_schema, "_revision_and_dispose", new=AsyncMock(return_value=None)
    ):
        assert verify_schema.verify() == 1


def test_it_fails_when_the_revision_cannot_be_read():
    """An unreachable database is not a pass. The gate must be closed, not open,
    when it cannot tell."""
    with patch.object(
        verify_schema,
        "_revision_and_dispose",
        new=AsyncMock(side_effect=OSError("connection refused")),
    ):
        assert verify_schema.verify() == 1


def test_it_fails_when_alembic_check_reports_drift():
    """The second question. The revision can be right while the schema is not —
    a hand-edited column, or a migration that does not describe what the models
    now declare."""
    from alembic.util.exc import AutogenerateDiffsDetected

    with patch.object(
        verify_schema,
        "check_for_drift",
        side_effect=AutogenerateDiffsDetected("Detected added column", None, []),
    ):
        assert verify_schema.verify() == 1


def test_a_drift_failure_names_the_difference(capsys):
    from alembic.util.exc import AutogenerateDiffsDetected

    with patch.object(
        verify_schema,
        "check_for_drift",
        side_effect=AutogenerateDiffsDetected("Detected added column 'x.y'", None, []),
    ):
        verify_schema.verify()

    assert "Detected added column 'x.y'" in capsys.readouterr().err


def test_a_stale_revision_failure_names_both_revisions(capsys):
    """The message has to be actionable at 3am: which revision the database is
    at, and which one the code wants."""
    with patch.object(
        verify_schema,
        "_revision_and_dispose",
        new=AsyncMock(return_value="000000000000"),
    ):
        verify_schema.verify()

    err = capsys.readouterr().err

    assert "000000000000" in err
    assert verify_schema.code_head() in err

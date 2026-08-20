"""add clinic subdomain

Revision ID: b8d2f4e61a09
Revises: c7a4e1f92b83
Create Date: 2026-08-20 19:05:00.000000

The tenant's DNS label, for routing by hostname later. Nothing routes on it
yet — this migration only creates the column and the guarantees it needs.

Nullable on purpose. Making it NOT NULL is a later step, after the application
and the test fixtures set it: 41 test files construct Clinic(...) directly, and
tightening the column before they do would break all of them at once.

The slug rules are DUPLICATED here rather than imported from
app/domain/clinics/subdomain.py. A migration has to keep producing the same
result years from now, against whatever the application looks like then; an
import would make this file's behaviour change when that module changes, and a
replay of history would no longer reproduce the schema it originally created.
"""
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8d2f4e61a09'
down_revision: Union[str, Sequence[str], None] = 'c7a4e1f92b83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The DNS limit for one label.
MAX_LENGTH = 63

# Frozen copy of the reserved set as it stood when this migration was written.
# The application's list will grow; this one must not, or a replay would
# produce different data than the original run did.
RESERVED = frozenset({
    "api", "www", "app", "web", "admin", "auth", "static", "assets", "cdn",
    "grafana", "prometheus", "alertmanager", "pushgateway", "metrics",
    "minio", "jaeger", "mailhog", "redis", "postgres", "db",
    "mail", "smtp", "imap", "pop", "mx", "ns", "ns1", "ns2", "dns", "email",
    "autodiscover", "autoconfig",
    "staging", "stage", "dev", "test", "demo", "sandbox", "preview", "local",
    "status", "health", "docs", "support", "help", "blog", "billing",
    "acme", "letsencrypt", "_acme-challenge",
})

_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


def _slugify(name: str) -> str:
    """A DNS label from a clinic name, or "" if nothing usable survives."""
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower())

    # Truncate before stripping: cutting at 63 can leave a trailing hyphen,
    # which is a malformed label.
    return slug[:MAX_LENGTH].strip("-")


def _unique_subdomain(base: str, clinic_id: int, taken: set[str]) -> str:
    """A free, valid, non-reserved label for this clinic."""
    if not base:
        base = f"clinic-{clinic_id}"

    candidate = base
    suffix = 1

    # A reserved name is treated exactly like a collision: the clinic cannot
    # have it, so it falls through to the numbered form.
    while candidate in taken or candidate in RESERVED or not _LABEL.match(candidate):
        suffix += 1
        tail = f"-{suffix}"
        candidate = f"{base[:MAX_LENGTH - len(tail)].strip('-')}{tail}"

    return candidate


def upgrade() -> None:
    op.add_column(
        "clinics",
        sa.Column("subdomain", sa.String(length=63), nullable=True),
    )

    # Backfill BEFORE the unique index and the CHECK exist, so a derived value
    # that somehow violated either would fail loudly here — with the clinic id
    # in scope — rather than as an opaque constraint error.
    bind = op.get_bind()

    rows = bind.execute(
        sa.text("SELECT id, name FROM clinics ORDER BY id")
    ).fetchall()

    taken: set[str] = set()

    for clinic_id, name in rows:
        subdomain = _unique_subdomain(_slugify(name), clinic_id, taken)
        taken.add(subdomain)

        bind.execute(
            sa.text("UPDATE clinics SET subdomain = :s WHERE id = :i"),
            {"s": subdomain, "i": clinic_id},
        )

    # Raw SQL, following uq_clinic_name_lower (a3bb7c81ba00): a functional
    # index cannot be expressed as unique=True on the column. DNS is
    # case-insensitive, so two rows differing only in case would be two tenants
    # claiming one host. NULLs are not compared, so any number of clinics may
    # have no subdomain.
    op.execute("""
        CREATE UNIQUE INDEX uq_clinic_subdomain_lower
        ON clinics (LOWER(subdomain));
    """)

    # The format rule restated in the database, so it also holds for a direct
    # SQL fix or a data import. Reserved names are deliberately NOT enforced
    # here: that list is a product decision that will change, and a constraint
    # on it would eventually reject rows that are already stored.
    op.create_check_constraint(
        "ck_clinics_subdomain_format",
        "clinics",
        "subdomain IS NULL OR subdomain ~ '^[a-z0-9]([a-z0-9-]*[a-z0-9])?$'",
    )


def downgrade() -> None:
    # Reverse order: the constraint and the index both depend on the column.
    op.drop_constraint(
        "ck_clinics_subdomain_format",
        "clinics",
        type_="check",
    )

    op.execute("""
        DROP INDEX IF EXISTS uq_clinic_subdomain_lower;
    """)

    op.drop_column("clinics", "subdomain")

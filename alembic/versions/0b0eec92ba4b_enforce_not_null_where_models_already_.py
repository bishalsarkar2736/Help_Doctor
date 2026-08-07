"""Make the schema enforce the NOT NULLs the models already declare.

Eleven columns were nullable in the database while their model declared them
required. The model was right in every case — a payment audit row with no
payment_id, or a prescription with no created_at, is not a state the
application can produce or the reader can interpret. The database simply was
not being asked to enforce it.

Left alone, this is the drift that makes `alembic revision --autogenerate`
produce ALTER statements nobody asked for on every future migration, which
trains whoever reviews them to skim. Correcting it deliberately, once, is what
lets the next generated migration be empty and therefore meaningful.

WHY THIS ABORTS INSTEAD OF BACKFILLING
Every column is checked for NULLs before anything is altered, and a single one
stops the migration with the table, column and count.

Backfilling would mean inventing values. For created_at that is a fabricated
timestamp in what is partly an audit trail; for payment_audit_logs.payment_id,
gateway, event_type and payload it is inventing the contents of a financial
audit record. Both are worse than stopping. If this aborts, the rows it names
are already wrong and a person should decide what they should have been.

The check runs first and DDL runs after, inside one transaction, so an abort
changes nothing.

Verified against the development database before writing: 0 NULLs in all
eleven. That is not a promise about production, which is exactly why the check
exists rather than an assumption.

A NOTE ON LOCKING
SET NOT NULL takes ACCESS EXCLUSIVE and scans the table. These tables are small
today. If they are large by the time this runs, the zero-downtime form is to
add a CHECK (col IS NOT NULL) NOT VALID, VALIDATE it without blocking reads and
writes, then SET NOT NULL — which Postgres 12+ can satisfy from the validated
constraint without a second scan. Not done here because the complexity is not
warranted at this size, and doing it invisibly would hide the trade-off.

Revision ID: 0b0eec92ba4b
Revises: 5fc78c7f911c
Create Date: 2026-08-07 23:12:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0b0eec92ba4b'
down_revision: Union[str, Sequence[str], None] = '5fc78c7f911c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column, postgres type as it must be restated for ALTER)
COLUMNS: list[tuple[str, str, sa.types.TypeEngine]] = [
    ("idempotency_keys", "created_at", sa.DateTime(timezone=True)),
    ("medicine_ai_error_logs", "clinic_id", sa.Integer()),
    ("medicine_assistant_queries", "clinic_id", sa.Integer()),
    ("payment_audit_logs", "payment_id", sa.Integer()),
    ("payment_audit_logs", "gateway", sa.String(length=20)),
    ("payment_audit_logs", "event_type", sa.String(length=50)),
    ("payment_audit_logs", "payload", sa.JSON()),
    ("payment_audit_logs", "created_at", sa.DateTime(timezone=True)),
    ("payments", "public_invoice_id", sa.String(length=36)),
    ("payments", "created_at", sa.DateTime(timezone=True)),
    ("prescriptions", "created_at", sa.DateTime(timezone=True)),
]


def upgrade() -> None:
    connection = op.get_bind()

    offenders = []

    for table, column, _ in COLUMNS:
        count = connection.execute(
            sa.text(f'SELECT count(*) FROM "{table}" WHERE "{column}" IS NULL')
        ).scalar()

        if count:
            offenders.append(f"{table}.{column} ({count} rows)")

    if offenders:
        raise RuntimeError(
            "Refusing to add NOT NULL: existing rows hold NULLs in "
            + ", ".join(offenders)
            + ". These columns are already declared required by the models, so "
            "those rows are in a state the application cannot produce. Decide "
            "what they should contain and correct them, then re-run. Nothing "
            "has been altered."
        )

    for table, column, type_ in COLUMNS:
        op.alter_column(table, column, existing_type=type_, nullable=False)


def downgrade() -> None:
    for table, column, type_ in COLUMNS:
        op.alter_column(table, column, existing_type=type_, nullable=True)

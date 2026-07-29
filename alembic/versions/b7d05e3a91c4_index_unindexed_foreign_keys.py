"""index unindexed foreign keys

Postgres indexes the *referenced* (primary key) side of a foreign key
automatically, but never the *referencing* column. Twelve FK columns had no
index, which costs on two separate paths:

1. **Reads.** Every lookup by the FK is a sequential scan —
   `refresh_tokens.user_id` alone is filtered at 39 call sites, and it is on
   the token-refresh path that every signed-in user hits continuously.

2. **Writes to the parent.** Deleting or updating a referenced row makes
   Postgres check each child table for referencing rows. Without an index that
   check is a full scan per constraint — and since the medical/financial FKs
   became RESTRICT, that check now runs on every such attempt.

Tables are small today (largest is refresh_tokens at ~24 rows), so this is
latent rather than urgent, which is exactly why it is cheap to fix now.

NOTE: plain CREATE INDEX takes a lock that blocks writes for the duration.
That is irrelevant at this size, but if you apply this to a table with
significant data, switch to CREATE INDEX CONCURRENTLY — which cannot run
inside a transaction, so it needs its own migration with autocommit.

Revision ID: b7d05e3a91c4
Revises: a91c47f2e6d8
Create Date: 2026-07-30

"""

from typing import Sequence, Union

from alembic import op

revision: str = "b7d05e3a91c4"
down_revision: Union[str, Sequence[str], None] = "a91c47f2e6d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column)
FK_COLUMNS = [
    ("appointment_status_history", "appointment_id"),
    ("appointment_status_history", "changed_by"),
    ("appointments", "cancelled_by"),
    ("doctors", "approved_by"),
    ("doctors", "rejected_by"),
    ("invitations", "accepted_user_id"),
    ("invitations", "invited_by_id"),
    ("notifications", "related_appointment_id"),
    ("payment_audit_logs", "payment_id"),
    ("payments", "patient_id"),
    ("prescription_items", "prescription_id"),
    ("refresh_tokens", "user_id"),
    # appointments.doctor_id appears "indexed" to a naive catalogue query
    # because it is the leading column of appointments_no_overlap -- but that
    # is a GiST index with a partial predicate (PENDING/CONFIRMED only), so it
    # cannot serve a plain "all appointments for this doctor" lookup. Verified
    # with enable_seqscan=off: the planner still chose a sequential scan.
    ("appointments", "doctor_id"),
]


def _name(table: str, column: str) -> str:
    return f"ix_{table}_{column}"


def upgrade() -> None:
    for table, column in FK_COLUMNS:
        op.create_index(_name(table, column), table, [column])


def downgrade() -> None:
    for table, column in FK_COLUMNS:
        op.drop_index(_name(table, column), table_name=table)

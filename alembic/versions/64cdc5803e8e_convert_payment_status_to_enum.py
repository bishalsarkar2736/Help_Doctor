"""convert payment status to enum

Revision ID: 64cdc5803e8e
Revises: 151b528c2859
Create Date: 2026-06-18 22:04:17.803050

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '64cdc5803e8e'
down_revision: Union[str, Sequence[str], None] = '151b528c2859'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


payment_status_enum = sa.Enum(
    "PENDING",
    "SUCCESS",
    "FAILED",
    "REFUNDED",
    name="payment_status",
)


def upgrade():

    # 1. Drop partial index
    op.drop_index(
        "idx_unique_pending_payment",
        table_name="payments",
    )

    payment_status = sa.Enum(
        "PENDING",
        "SUCCESS",
        "FAILED",
        "REFUNDED",
        name="payment_status",
    )

    payment_status.create(
        op.get_bind(),
        checkfirst=True,
    )

    # 2. Remove old default
    op.execute("""
        ALTER TABLE payments
        ALTER COLUMN status DROP DEFAULT
    """)

    # 3. Convert column
    op.execute("""
        ALTER TABLE payments
        ALTER COLUMN status
        TYPE payment_status
        USING status::payment_status
    """)

    # 4. Restore default
    op.execute("""
        ALTER TABLE payments
        ALTER COLUMN status
        SET DEFAULT 'PENDING'
    """)

    op.alter_column(
        "payments",
        "status",
        nullable=False,
    )

    # 5. Recreate partial index
    op.create_index(
        "idx_unique_pending_payment",
        "payments",
        ["appointment_id"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'PENDING'"
        ),
    )


def downgrade():

    op.drop_index(
        "idx_unique_pending_payment",
        table_name="payments",
    )

    op.execute("""
        ALTER TABLE payments
        ALTER COLUMN status DROP DEFAULT
    """)

    op.execute("""
        ALTER TABLE payments
        ALTER COLUMN status
        TYPE VARCHAR(20)
        USING status::text
    """)

    op.execute("""
        ALTER TABLE payments
        ALTER COLUMN status
        SET DEFAULT 'PENDING'
    """)

    op.execute(
        "DROP TYPE payment_status"
    )

    op.create_index(
        "idx_unique_pending_payment",
        "payments",
        ["appointment_id"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'PENDING'"
        ),
    )
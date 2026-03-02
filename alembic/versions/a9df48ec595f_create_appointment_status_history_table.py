"""create appointment_status_history table

Revision ID: a9df48ec595f
Revises: 1a20dc9f1e5a
Create Date: 2026-02-23 12:00:56.641848

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a9df48ec595f'
down_revision: Union[str, Sequence[str], None] = '1a20dc9f1e5a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1️⃣ Create new table
    appointment_status_enum = postgresql.ENUM(
        'PENDING',
        'CONFIRMED',
        'CANCELLED',
        'COMPLETED',
        'SCHEDULED',
        'NO_SHOW',
        name='appointmentstatus',
        create_type=False  # important
    )
    op.create_table(
        'appointment_status_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('appointment_id', sa.Integer(), nullable=False),
        sa.Column('old_status',appointment_status_enum, nullable=False),
        sa.Column('new_status',appointment_status_enum, nullable=False),
        sa.Column('changed_by', sa.Integer(), nullable=True),
        sa.Column('changed_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['changed_by'], ['users.id']),
    )

    # 2️⃣ Migrate data (safe even if 0 rows)
    op.execute("""
        INSERT INTO appointment_status_history (
            appointment_id,
            old_status,
            new_status,
            changed_by,
            changed_at
        )
        SELECT
            appointment_id,
            from_status::appointmentstatus,
            to_status::appointmentstatus,
            changed_by,
            created_at
        FROM appointment_audit_log
    """)

    # 3️⃣ Drop old table
    op.drop_index(
        op.f('ix_appointment_audit_log_appointment_id'),
        table_name='appointment_audit_log'
    )
    op.drop_table('appointment_audit_log')

    # 4️⃣ Alter column
    op.alter_column(
        'appointments',
        'time_range',
        existing_type=postgresql.TSTZRANGE(),
        nullable=False
    )


def downgrade() -> None:

    # 1️⃣ Revert time_range constraint
    op.alter_column(
        'appointments',
        'time_range',
        existing_type=postgresql.TSTZRANGE(),
        nullable=True
    )

    # 2️⃣ Recreate old table
    op.create_table(
        'appointment_audit_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('appointment_id', sa.Integer(), nullable=False),
        sa.Column('from_status', sa.String(length=32), nullable=False),
        sa.Column('to_status', sa.String(length=32), nullable=False),
        sa.Column('changed_by', sa.Integer(), nullable=False),
        sa.Column('actor_role', sa.String(length=16), nullable=False),
        sa.Column('is_idempotent', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('appointment_audit_log_pkey'))
    )

    # 3️⃣ Copy data back
    op.execute("""
        INSERT INTO appointment_audit_log (
            appointment_id,
            from_status,
            to_status,
            changed_by,
            created_at
        )
        SELECT
            appointment_id,
            old_status,
            new_status,
            changed_by,
            changed_at
        FROM appointment_status_history
    """)

    # 4️⃣ Recreate index
    op.create_index(
        op.f('ix_appointment_audit_log_appointment_id'),
        'appointment_audit_log',
        ['appointment_id'],
        unique=False
    )

    # 5️⃣ Drop new table
    op.drop_table('appointment_status_history')
    
    # ### end Alembic commands ###

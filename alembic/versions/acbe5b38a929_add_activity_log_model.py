"""add activity log model

Revision ID: acbe5b38a929
Revises: 3d697838bb39
Create Date: 2026-06-12 22:26:39.897664

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'acbe5b38a929'
down_revision: Union[str, Sequence[str], None] = '3d697838bb39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade():

    op.create_table(
        "activity_logs",

        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
        ),

        sa.Column(
            "clinic_id",
            sa.Integer(),
            nullable=True,
        ),

        sa.Column(
            "actor_id",
            sa.Integer(),
            nullable=True,
        ),

        sa.Column(
            "action",
            sa.String(length=100),
            nullable=False,
        ),

        sa.Column(
            "entity_type",
            sa.String(length=50),
            nullable=False,
        ),

        sa.Column(
            "entity_id",
            sa.Integer(),
            nullable=True,
        ),

        sa.Column(
            "details",
            sa.Text(),
            nullable=True,
        ),

        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinics.id"],
            name="fk_activity_logs_clinic_id",
            ondelete="SET NULL",
        ),

        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name="fk_activity_logs_actor_id",
            ondelete="SET NULL",
        ),
    )

    op.create_index(
        "ix_activity_logs_clinic_id",
        "activity_logs",
        ["clinic_id"],
    )

    op.create_index(
        "ix_activity_logs_actor_id",
        "activity_logs",
        ["actor_id"],
    )

    op.create_index(
        "ix_activity_logs_action",
        "activity_logs",
        ["action"],
    )

    op.create_index(
        "ix_activity_logs_entity_type",
        "activity_logs",
        ["entity_type"],
    )

    op.create_index(
        "ix_activity_logs_entity_id",
        "activity_logs",
        ["entity_id"],
    )


def downgrade():

    op.drop_index(
        "ix_activity_logs_entity_id",
        table_name="activity_logs",
    )

    op.drop_index(
        "ix_activity_logs_entity_type",
        table_name="activity_logs",
    )

    op.drop_index(
        "ix_activity_logs_action",
        table_name="activity_logs",
    )

    op.drop_index(
        "ix_activity_logs_actor_id",
        table_name="activity_logs",
    )

    op.drop_index(
        "ix_activity_logs_clinic_id",
        table_name="activity_logs",
    )

    op.drop_table(
        "activity_logs",
    )
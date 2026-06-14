"""create prescription templates

Revision ID: 655f4a885bd5
Revises: acbe5b38a929
Create Date: 2026-06-14 00:54:00.869464

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '655f4a885bd5'
down_revision: Union[str, Sequence[str], None] = 'acbe5b38a929'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():

    op.create_table(
        "prescription_templates",

        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
        ),

        sa.Column(
            "doctor_id",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "clinic_id",
            sa.Integer(),
            nullable=True,
        ),

        sa.Column(
            "name",
            sa.String(length=255),
            nullable=False,
        ),

        sa.Column(
            "notes",
            sa.Text(),
            nullable=True,
        ),

        sa.ForeignKeyConstraint(
            ["doctor_id"],
            ["doctors.id"],
            ondelete="CASCADE",
        ),

        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinics.id"],
            ondelete="SET NULL",
        ),
    )

    op.create_index(
        "ix_prescription_templates_doctor_id",
        "prescription_templates",
        ["doctor_id"],
    )

    op.create_index(
        "ix_prescription_templates_clinic_id",
        "prescription_templates",
        ["clinic_id"],
    )

    op.create_table(
        "prescription_template_items",

        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
        ),

        sa.Column(
            "template_id",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "medicine_name",
            sa.String(length=255),
            nullable=False,
        ),

        sa.Column(
            "dosage",
            sa.String(length=100),
            nullable=True,
        ),

        sa.Column(
            "frequency",
            sa.String(length=100),
            nullable=True,
        ),

        sa.Column(
            "duration_days",
            sa.Integer(),
            nullable=True,
        ),

        sa.Column(
            "instructions",
            sa.Text(),
            nullable=True,
        ),

        sa.ForeignKeyConstraint(
            ["template_id"],
            ["prescription_templates.id"],
            ondelete="CASCADE",
        ),
    )

    op.create_index(
        "ix_prescription_template_items_template_id",
        "prescription_template_items",
        ["template_id"],
    )


def downgrade():

    op.drop_table(
        "prescription_template_items"
    )

    op.drop_table(
        "prescription_templates"
    )
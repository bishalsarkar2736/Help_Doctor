"""add doctor credential documents

Revision ID: d5e8b3c71f42
Revises: c1f4a7e93d20
Create Date: 2026-07-28 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d5e8b3c71f42"
down_revision: Union[str, Sequence[str], None] = "c1f4a7e93d20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


doc_type_enum = postgresql.ENUM(
    "BMDC_CERTIFICATE",
    "DEGREE",
    "LICENSE",
    "OTHER",
    name="doctor_document_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    doc_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "doctor_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "doctor_id",
            sa.Integer(),
            sa.ForeignKey("doctors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("doc_type", doc_type_enum, nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_doctor_documents_doctor_id", "doctor_documents", ["doctor_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_doctor_documents_doctor_id", table_name="doctor_documents")
    op.drop_table("doctor_documents")
    doc_type_enum.drop(op.get_bind(), checkfirst=True)

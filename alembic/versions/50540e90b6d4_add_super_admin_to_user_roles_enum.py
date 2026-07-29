"""add super_admin to user_roles enum

Revision ID: 50540e90b6d4
Revises: c52e2e07e39e
Create Date: 2026-07-23 12:30:02.522659

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '50540e90b6d4'
down_revision: Union[str, Sequence[str], None] = 'c52e2e07e39e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add SUPER_ADMIN label to the user_roles enum type.

    SQLAlchemy persists the enum member *name*, so the DB label is the
    uppercase 'SUPER_ADMIN' (matching UserRole.SUPER_ADMIN).
    """
    op.execute(
        "ALTER TYPE user_roles ADD VALUE IF NOT EXISTS 'SUPER_ADMIN'"
    )


def downgrade() -> None:
    """Postgres does not support removing enum values; no-op.

    (Mirrors the project's existing enum-value migrations.)
    """
    pass

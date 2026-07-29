"""patient gender enum and dob date

Revision ID: c9b2e0c7f5b8
Revises: fbf361fb7bd6
Create Date: 2026-07-24 12:05:18.669405

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c9b2e0c7f5b8'
down_revision: Union[str, Sequence[str], None] = 'fbf361fb7bd6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


gender_enum = postgresql.ENUM(
    "MALE", "FEMALE", "OTHER",
    name="gender",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()

    gender_enum.create(bind, checkfirst=True)

    # gender: free-form varchar -> enum (uppercasing existing values).
    op.execute(
        "ALTER TABLE patients "
        "ALTER COLUMN gender TYPE gender "
        "USING (upper(gender))::gender"
    )

    # date_of_birth: varchar 'YYYY-MM-DD' -> DATE.
    op.execute(
        "ALTER TABLE patients "
        "ALTER COLUMN date_of_birth TYPE date "
        "USING date_of_birth::date"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE patients "
        "ALTER COLUMN date_of_birth TYPE varchar(20) "
        "USING date_of_birth::text"
    )
    op.execute(
        "ALTER TABLE patients "
        "ALTER COLUMN gender TYPE varchar(10) "
        "USING gender::text"
    )

    bind = op.get_bind()
    gender_enum.drop(bind, checkfirst=True)

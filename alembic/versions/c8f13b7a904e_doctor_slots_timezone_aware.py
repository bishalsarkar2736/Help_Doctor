"""make doctor_slots timestamps timezone-aware

doctor_slots.start_time / end_time were `timestamp without time zone`, while
every other timestamp in the schema is `timestamptz`.

The mismatch broke patient booking outright:

  slot_generation converts clinic-local availability to UTC and writes
  UTC-aware datetimes, but the naive column dropped the offset on write.
  get_doctor_slots then filtered with UTC-aware bounds, and asyncpg refused to
  bind an aware datetime against a naive column:

      DataError: can't subtract offset-naive and offset-aware datetimes

  GET /slots/doctors/{id}/slots returned 500, so the booking screen showed no
  slots at all. Because a 500 carries no CORS headers, browsers reported it as
  a cross-origin failure rather than a server error, which hid the real cause.

Existing values are interpreted as UTC, matching what slot_generation always
intended to store.

Revision ID: c8f13b7a904e
Revises: b7d05e3a91c4
Create Date: 2026-07-30

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8f13b7a904e"
down_revision: Union[str, Sequence[str], None] = "b7d05e3a91c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for column in ("start_time", "end_time"):
        op.execute(
            f"ALTER TABLE doctor_slots "
            f"ALTER COLUMN {column} TYPE TIMESTAMP WITH TIME ZONE "
            f"USING {column} AT TIME ZONE 'UTC'"
        )


def downgrade() -> None:
    for column in ("start_time", "end_time"):
        op.execute(
            f"ALTER TABLE doctor_slots "
            f"ALTER COLUMN {column} TYPE TIMESTAMP WITHOUT TIME ZONE "
            f"USING {column} AT TIME ZONE 'UTC'"
        )

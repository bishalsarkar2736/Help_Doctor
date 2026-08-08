"""Drop doctor_slots.is_booked. Availability is derived from appointments.

Nothing ever wrote True to this column — not application code, not a trigger,
not a migration. Every slot therefore reported itself free forever: the public
slot list offered booked times, only_available filtered nothing, the assistant
recommended occupied slots, and doctor utilisation was permanently zero.
Patients picked a slot the screen called free and were then refused by the
exclusion constraint.

It is dropped rather than fixed in place. A stored flag is a second copy of what
the appointments table already holds, and the two diverge the first time any
booking, cancellation or reschedule path forgets to update it — which is how
this ended up empty in the first place. Occupancy is now a predicate over
appointments (app/domain/scheduling/occupancy.py) using the same status set as
the exclusion constraint, so a slot cannot claim to be free while the database
refuses to book it.

NO DATA IS LOST
Every row holds false, because false is the default and nothing ever changed it.
Verified before writing this: 0 rows with is_booked = true. Dropping the column
therefore removes no information — only the opportunity to read a value that was
never true.

Dropping it, rather than leaving it unused, is also what makes "there is no
second source of truth" checkable instead of a convention: a column that does
not exist cannot be read by mistake, and tests/test_schema_drift.py asserts it
stays gone.

Revision ID: 0562f48dd3b6
Revises: 19cfc561fcac
Create Date: 2026-08-08 00:15:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0562f48dd3b6'
down_revision: Union[str, Sequence[str], None] = '19cfc561fcac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()

    # Refuse to drop a column that turns out to hold real state somewhere.
    # If any row is true, this database is not the one this migration was
    # written against and somebody should look before information is discarded.
    booked = connection.execute(
        sa.text("SELECT count(*) FROM doctor_slots WHERE is_booked IS TRUE")
    ).scalar()

    if booked:
        raise RuntimeError(
            f"doctor_slots.is_booked is true on {booked} row(s). This column "
            f"was believed to be written by nothing, so dropping it would "
            f"discard state that is apparently in use. Nothing has been "
            f"altered — establish where those values came from first."
        )

    op.drop_column("doctor_slots", "is_booked")


def downgrade() -> None:
    # Restored with its original default. Every row was false, so re-creating
    # the column reproduces the previous contents exactly — and, with nothing
    # writing to it, the previous bug.
    op.add_column(
        "doctor_slots",
        sa.Column(
            "is_booked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

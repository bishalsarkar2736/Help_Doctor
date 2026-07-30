"""GET /slots/doctors/{id}/slots must not 500.

This endpoint feeds the patient booking screen. It returned 500 for every
request because doctor_slots.start_time was `timestamp without time zone` while
the query filtered with UTC-aware bounds, and asyncpg refuses to bind an aware
datetime against a naive column.

Nothing caught it: the backend suite never called the endpoint, and in the
browser a 500 carries no CORS headers, so it surfaced as an opaque
"blocked by CORS" error rather than a server error.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.doctor_slot import DoctorSlot


@pytest.mark.asyncio
async def test_listing_slots_succeeds(client, db, auth_doctor):
    doctor_id = auth_doctor["doctor"].id
    start = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0)

    db.add(
        DoctorSlot(
            doctor_id=doctor_id,
            start_time=start,
            end_time=start + timedelta(minutes=30),
            is_booked=False,
        )
    )
    await db.commit()

    response = await client.get(
        f"/slots/doctors/{doctor_id}/slots",
        params={
            "start_date": start.date().isoformat(),
            "days": 7,
            "only_available": True,
        },
    )

    assert response.status_code == 200, response.text
    assert len(response.json()) >= 1


@pytest.mark.asyncio
async def test_stored_slot_times_keep_their_offset(db, auth_doctor):
    """A naive column silently discarded tzinfo on write."""

    start = datetime.now(UTC).replace(microsecond=0)
    db.add(
        DoctorSlot(
            doctor_id=auth_doctor["doctor"].id,
            start_time=start,
            end_time=start + timedelta(minutes=30),
            is_booked=False,
        )
    )
    await db.commit()

    stored = await db.scalar(
        select(DoctorSlot).where(DoctorSlot.doctor_id == auth_doctor["doctor"].id)
    )

    assert stored.start_time.tzinfo is not None, "offset was dropped on write"
    assert stored.start_time == start


@pytest.mark.asyncio
async def test_empty_range_returns_an_empty_list_not_an_error(
    client, auth_doctor
):
    response = await client.get(
        f"/slots/doctors/{auth_doctor['doctor'].id}/slots",
        params={"start_date": "2030-01-01", "days": 1, "only_available": True},
    )

    assert response.status_code == 200, response.text
    assert response.json() == []

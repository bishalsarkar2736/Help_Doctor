"""Admins recording when their clinic is open.

Until this existed the schema could hold opening hours but nothing could write
them, so the assistant's honest answer to "when do you close?" was always "I
don't know". These are the endpoints that make it answerable.

The write is a REPLACE. With a partial update there is no way to say "we no
longer open on Sunday" — a removed weekday and an unmentioned one look
identical — so a clinic could add hours and never take them away.
"""

import pytest
from sqlalchemy import select

from app.models.clinic import Clinic

MONDAY_SPLIT = {
    "days": {
        "0": [
            {"open": "09:00", "close": "13:00"},
            {"open": "16:00", "close": "21:00"},
        ],
        "1": [{"open": "09:00", "close": "17:00"}],
    }
}

HOLIDAYS = {
    "holidays": [
        {"date": "2026-12-16", "name": "Victory Day"},
        {"date": "2026-03-26", "name": "Independence Day"},
    ]
}


async def _put_hours(client, auth_admin, clinic_id, body):
    return await client.put(
        "/admin/clinic/opening-hours",
        params={"clinic_id": clinic_id},
        json=body,
        headers=auth_admin["headers"],
    )


async def _put_holidays(client, auth_admin, clinic_id, body):
    return await client.put(
        "/admin/clinic/holidays",
        params={"clinic_id": clinic_id},
        json=body,
        headers=auth_admin["headers"],
    )


@pytest.fixture
def clinic_id(auth_admin):
    return auth_admin["user"].clinic_id


# ---------------------------------------------------------------------------
# Opening hours
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hours_start_unconfigured(client, auth_admin, clinic_id):
    """A clinic that has set nothing must be distinguishable from a shut one."""
    res = await client.get(
        "/admin/clinic/opening-hours",
        params={"clinic_id": clinic_id},
        headers=auth_admin["headers"],
    )

    assert res.status_code == 200, res.text
    assert res.json()["is_configured"] is False


@pytest.mark.asyncio
async def test_an_admin_can_record_hours(client, auth_admin, clinic_id):
    res = await _put_hours(client, auth_admin, clinic_id, MONDAY_SPLIT)

    assert res.status_code == 200, res.text

    body = res.json()
    assert body["is_configured"] is True
    assert len(body["days"][0]["ranges"]) == 2


@pytest.mark.asyncio
async def test_hours_persist(client, db, auth_admin, clinic_id):
    await _put_hours(client, auth_admin, clinic_id, MONDAY_SPLIT)

    clinic = await db.scalar(select(Clinic).where(Clinic.id == clinic_id))
    await db.refresh(clinic)

    assert clinic.opening_hours["0"][0]["open"] == "09:00"


@pytest.mark.asyncio
async def test_a_write_replaces_rather_than_merges(client, auth_admin, clinic_id):
    """Removing a day has to be possible."""
    await _put_hours(client, auth_admin, clinic_id, MONDAY_SPLIT)

    res = await _put_hours(
        client,
        auth_admin,
        clinic_id,
        {"days": {"1": [{"open": "10:00", "close": "12:00"}]}},
    )

    days = res.json()["days"]
    assert days[0]["is_closed"] is True
    assert days[1]["ranges"] == [{"open": "10:00", "close": "12:00"}]


@pytest.mark.asyncio
async def test_hours_can_be_cleared(client, auth_admin, clinic_id):
    await _put_hours(client, auth_admin, clinic_id, MONDAY_SPLIT)

    res = await _put_hours(client, auth_admin, clinic_id, {"days": {}})

    assert res.json()["is_configured"] is False


# ---------------------------------------------------------------------------
# Refused input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_close_before_its_open_is_refused(client, auth_admin, clinic_id):
    res = await _put_hours(
        client,
        auth_admin,
        clinic_id,
        {"days": {"0": [{"open": "17:00", "close": "09:00"}]}},
    )

    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_overlapping_ranges_are_refused(client, auth_admin, clinic_id):
    res = await _put_hours(
        client,
        auth_admin,
        clinic_id,
        {
            "days": {
                "0": [
                    {"open": "09:00", "close": "14:00"},
                    {"open": "13:00", "close": "18:00"},
                ]
            }
        },
    )

    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_an_invalid_weekday_is_refused(client, auth_admin, clinic_id):
    res = await _put_hours(
        client,
        auth_admin,
        clinic_id,
        {"days": {"9": [{"open": "09:00", "close": "17:00"}]}},
    )

    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_bad_hours_do_not_overwrite_good_ones(client, auth_admin, clinic_id):
    """A rejected write must leave what was there intact."""
    await _put_hours(client, auth_admin, clinic_id, MONDAY_SPLIT)

    await _put_hours(
        client,
        auth_admin,
        clinic_id,
        {"days": {"0": [{"open": "17:00", "close": "09:00"}]}},
    )

    res = await client.get(
        "/admin/clinic/opening-hours",
        params={"clinic_id": clinic_id},
        headers=auth_admin["headers"],
    )

    assert len(res.json()["days"][0]["ranges"]) == 2


# ---------------------------------------------------------------------------
# Holidays
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_holidays_can_be_recorded_and_are_ordered(
    client, auth_admin, clinic_id
):
    res = await _put_holidays(client, auth_admin, clinic_id, HOLIDAYS)

    assert res.status_code == 200, res.text
    assert [h["date"] for h in res.json()] == ["2026-03-26", "2026-12-16"]


@pytest.mark.asyncio
async def test_duplicate_holiday_dates_are_refused(client, auth_admin, clinic_id):
    res = await _put_holidays(
        client,
        auth_admin,
        clinic_id,
        {
            "holidays": [
                {"date": "2026-03-26", "name": "One"},
                {"date": "2026-03-26", "name": "Two"},
            ]
        },
    )

    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_holidays_can_be_cleared(client, auth_admin, clinic_id):
    await _put_holidays(client, auth_admin, clinic_id, HOLIDAYS)

    res = await _put_holidays(client, auth_admin, clinic_id, {"holidays": []})

    assert res.json() == []


# ---------------------------------------------------------------------------
# Authorization and tenancy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_doctor_cannot_set_hours(client, auth_doctor, auth_admin, clinic_id):
    res = await client.put(
        "/admin/clinic/opening-hours",
        params={"clinic_id": clinic_id},
        json=MONDAY_SPLIT,
        headers=auth_doctor["headers"],
    )

    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_an_anonymous_caller_cannot_set_hours(client, clinic_id):
    res = await client.put(
        "/admin/clinic/opening-hours",
        params={"clinic_id": clinic_id},
        json=MONDAY_SPLIT,
    )

    assert res.status_code == 401, res.text


@pytest.mark.asyncio
async def test_an_admin_cannot_edit_another_clinic(client, db, auth_admin):
    """Tenancy is enforced by the same resolver the rest of the admin API uses."""
    from app.models.clinic import ClinicStatus

    other = Clinic(name="Someone Else's Clinic", status=ClinicStatus.ACTIVE)
    db.add(other)
    await db.commit()

    res = await _put_hours(client, auth_admin, other.id, MONDAY_SPLIT)

    assert res.status_code == 403, res.text

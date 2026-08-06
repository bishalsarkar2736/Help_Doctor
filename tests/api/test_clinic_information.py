"""What a clinic publishes: contact details, opening hours, holidays.

Every answer here is stated to a patient as fact — "we close at 9 PM", "we're
closed on Friday". The point of putting the backend in front of the model is
that these come from what a clinic recorded, and that anything it did not
record comes back as unknown rather than as a plausible guess.
"""

from datetime import date, datetime, timezone

import pytest

from app.models.clinic import Clinic, ClinicStatus
from app.schemas.clinic_hours_schema import (
    HolidayScheduleUpdate,
    OpeningHoursUpdate,
)
from app.services.clinic_information_service import (
    get_clinic_holiday_schedule,
    get_clinic_information,
    get_clinic_opening_hours,
    holiday_on,
    is_open_at,
)

# Monday 09:00-13:00 and 16:00-21:00 — the split day that a single open/close
# pair could not express.
HOURS = {
    "0": [
        {"open": "09:00", "close": "13:00"},
        {"open": "16:00", "close": "21:00"},
    ],
    "1": [{"open": "09:00", "close": "17:00"}],
}

HOLIDAYS = [{"date": "2026-03-26", "name": "Independence Day"}]


def _clinic(**overrides) -> Clinic:
    defaults = dict(
        id=1,
        name="Dhaka Clinic",
        address="12 Gulshan Ave",
        phone="+8801700000000",
        email="hello@clinic.test",
        website="https://clinic.test",
        timezone="Asia/Dhaka",
        status=ClinicStatus.ACTIVE,
        opening_hours=HOURS,
        holiday_schedule=HOLIDAYS,
    )
    defaults.update(overrides)
    return Clinic(**defaults)


def _at(iso: str) -> datetime:
    """A UTC instant, so the local conversion is what is under test."""
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Contact details
# ---------------------------------------------------------------------------


def test_contact_details_are_returned():
    info = get_clinic_information(_clinic())

    assert info["name"] == "Dhaka Clinic"
    assert info["address"] == "12 Gulshan Ave"
    assert info["phone"] == "+8801700000000"


def test_no_patient_data_is_exposed():
    """Version 1 answers only what a clinic already advertises."""
    info = get_clinic_information(_clinic())

    forbidden = {"patients", "appointments", "prescriptions", "doctors"}
    assert forbidden.isdisjoint(info)


# ---------------------------------------------------------------------------
# Opening hours
# ---------------------------------------------------------------------------


def test_every_weekday_is_reported():
    hours = get_clinic_opening_hours(_clinic())

    assert len(hours["days"]) == 7
    assert hours["days"][0]["name"] == "Monday"


def test_a_split_day_keeps_both_ranges():
    """Closing for lunch is the normal pattern, not an edge case."""
    hours = get_clinic_opening_hours(_clinic())

    assert len(hours["days"][0]["ranges"]) == 2


def test_a_day_with_no_hours_is_closed():
    hours = get_clinic_opening_hours(_clinic())

    assert hours["days"][6]["is_closed"] is True


def test_unconfigured_hours_are_distinguishable_from_closed():
    """"Closed all week" and "never set up" need different answers."""
    assert get_clinic_opening_hours(_clinic())["is_configured"] is True
    assert get_clinic_opening_hours(_clinic(opening_hours={}))["is_configured"] is False


# ---------------------------------------------------------------------------
# Open now
# ---------------------------------------------------------------------------


def test_open_during_a_range():
    """2026-03-09 is a Monday. 05:00 UTC is 11:00 in Dhaka."""
    result = is_open_at(_clinic(), _at("2026-03-09T05:00:00"))

    assert result["is_open"] is True
    assert result["closes_at"] == "13:00"


def test_closed_during_the_lunch_gap():
    """08:00 UTC is 14:00 local — after the morning range, before the evening."""
    result = is_open_at(_clinic(), _at("2026-03-09T08:00:00"))

    assert result["is_open"] is False
    assert result["reason"] == "outside_opening_hours"


def test_open_again_in_the_evening_range():
    """14:00 UTC is 20:00 local."""
    result = is_open_at(_clinic(), _at("2026-03-09T14:00:00"))

    assert result["is_open"] is True


def test_the_local_timezone_decides_not_the_servers():
    """20:00 UTC on Sunday is already 02:00 Monday in Dhaka.

    Judged in UTC this is Sunday, when the clinic is closed. Judged locally it
    is Monday — still closed, but before opening rather than on a closed day,
    and the day it belongs to is different.
    """
    result = is_open_at(_clinic(), _at("2026-03-08T20:00:00"))

    assert result["is_open"] is False
    assert result["reason"] == "outside_opening_hours"
    assert result["local_time"].startswith("2026-03-09")


def test_a_closed_weekday_says_so():
    """Sunday has no ranges at all."""
    result = is_open_at(_clinic(), _at("2026-03-15T05:00:00"))

    assert result["is_open"] is False
    assert result["reason"] == "closed_today"


def test_a_holiday_closes_the_clinic():
    """2026-03-26 is a Thursday, but the clinic is shut for the day."""
    clinic = _clinic(
        opening_hours={**HOURS, "3": [{"open": "09:00", "close": "17:00"}]}
    )

    result = is_open_at(clinic, _at("2026-03-26T05:00:00"))

    assert result["is_open"] is False
    assert result["reason"] == "holiday"
    assert result["holiday"]["name"] == "Independence Day"


def test_unknown_hours_answer_unknown_not_closed():
    """A clinic that never recorded hours is not the same as a shut one.

    Answering "closed" would turn a gap in the data into a statement of fact.
    """
    result = is_open_at(_clinic(opening_hours={}), _at("2026-03-09T05:00:00"))

    assert result["is_open"] is None
    assert result["reason"] == "opening_hours_not_configured"


def test_an_unparseable_range_does_not_break_the_answer():
    """One bad row must not take down every question about the clinic."""
    clinic = _clinic(opening_hours={"0": [{"open": "nine", "close": "13:00"}]})

    result = is_open_at(clinic, _at("2026-03-09T05:00:00"))

    assert result["is_open"] is False


# ---------------------------------------------------------------------------
# Holidays
# ---------------------------------------------------------------------------


def test_holidays_are_returned_earliest_first():
    clinic = _clinic(
        holiday_schedule=[
            {"date": "2026-12-16", "name": "Victory Day"},
            {"date": "2026-03-26", "name": "Independence Day"},
        ]
    )

    assert [h["date"] for h in get_clinic_holiday_schedule(clinic)] == [
        "2026-03-26",
        "2026-12-16",
    ]


def test_holiday_lookup_finds_the_day():
    assert holiday_on(_clinic(), date(2026, 3, 26))["name"] == "Independence Day"


def test_holiday_lookup_returns_none_otherwise():
    assert holiday_on(_clinic(), date(2026, 3, 27)) is None


# ---------------------------------------------------------------------------
# Write validation
# ---------------------------------------------------------------------------


def test_a_close_before_its_open_is_refused():
    with pytest.raises(ValueError, match="must be after"):
        OpeningHoursUpdate(days={0: [{"open": "17:00", "close": "09:00"}]})


def test_overlapping_ranges_are_refused():
    """Always a data-entry mistake, and it makes "when do you close?" ambiguous."""
    with pytest.raises(ValueError, match="overlapping"):
        OpeningHoursUpdate(
            days={
                0: [
                    {"open": "09:00", "close": "14:00"},
                    {"open": "13:00", "close": "18:00"},
                ]
            }
        )


def test_an_out_of_range_weekday_is_refused():
    with pytest.raises(ValueError, match="Monday"):
        OpeningHoursUpdate(days={7: [{"open": "09:00", "close": "17:00"}]})


def test_storage_form_uses_string_keys():
    """JSON objects have no integer keys; the reader looks up str(weekday)."""
    stored = OpeningHoursUpdate(
        days={0: [{"open": "09:00", "close": "17:00"}]}
    ).to_storage()

    assert stored == {"0": [{"open": "09:00", "close": "17:00"}]}


def test_an_empty_weekday_is_not_stored():
    """Absent and empty both mean closed; storing both gives two ways to say it."""
    stored = OpeningHoursUpdate(days={0: [], 1: [{"open": "09:00", "close": "17:00"}]})

    assert stored.to_storage() == {"1": [{"open": "09:00", "close": "17:00"}]}


def test_duplicate_holiday_dates_are_refused():
    with pytest.raises(ValueError, match="duplicate"):
        HolidayScheduleUpdate(
            holidays=[
                {"date": "2026-03-26", "name": "Independence Day"},
                {"date": "2026-03-26", "name": "Also Independence Day"},
            ]
        )


def test_holidays_are_stored_in_date_order():
    stored = HolidayScheduleUpdate(
        holidays=[
            {"date": "2026-12-16", "name": "Victory Day"},
            {"date": "2026-03-26", "name": "Independence Day"},
        ]
    ).to_storage()

    assert [entry["date"] for entry in stored] == ["2026-03-26", "2026-12-16"]

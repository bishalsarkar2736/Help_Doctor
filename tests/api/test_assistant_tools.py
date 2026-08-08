"""The only things the scheduling assistant can ask the backend.

Two properties matter more than the happy paths.

Tenancy: every tool takes a resolved clinic, and none of them may return
anything belonging to another one. This is a multi-tenant SaaS, not a
marketplace, so a helpful suggestion from the clinic next door is a breach.

Emptiness: "nothing found" is a real answer with its own status, so the layer
above relays it rather than reaching for something close enough.
"""

from datetime import date, datetime, timedelta

import pytest

from app.assistant.tools import (
    clinic_information,
    clinic_today,
    doctor_availability,
    earliest_slot,
    list_specializations,
    search_doctors,
)
from app.core.time import UTC, utc_now
from app.models.clinic import Clinic, ClinicStatus
from app.models.doctor import Doctor, DoctorStatus
from app.models.doctor_slot import DoctorSlot
from app.models.user import User, UserRole

HOURS = {"0": [{"open": "09:00", "close": "17:00"}]}


@pytest.fixture
async def clinics(db):
    made = {}

    for key, name in (("ours", "Our Clinic"), ("theirs", "Their Clinic")):
        clinic = Clinic(
            name=name,
            status=ClinicStatus.ACTIVE,
            timezone="Asia/Dhaka",
            address="12 Gulshan Ave",
            phone="+8801700000000",
            opening_hours=HOURS if key == "ours" else {},
        )
        db.add(clinic)
        await db.flush()
        made[key] = clinic

    await db.commit()
    return made


async def _doctor(
    db,
    clinic,
    *,
    email,
    name,
    specialization="Cardiology",
    status=DoctorStatus.APPROVED,
    is_active=True,
):
    user = User(
        email=email,
        full_name=name,
        hashed_password="x",
        role=UserRole.DOCTOR,
        is_active=is_active,
    )
    db.add(user)
    await db.flush()

    doctor = Doctor(
        user_id=user.id,
        clinic_id=clinic.id,
        specialization=specialization,
        experience_years=7,
        bio="Doctor",
        status=status,
    )
    db.add(doctor)
    await db.flush()
    return doctor


async def _slot(db, doctor, *, at: datetime):
    db.add(
        DoctorSlot(
            doctor_id=doctor.id,
            start_time=at,
            end_time=at + timedelta(minutes=30),
        )
    )
    await db.flush()


# ---------------------------------------------------------------------------
# search_doctors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_returns_this_clinics_doctors(db, clinics):
    await _doctor(db, clinics["ours"], email="a@t.com", name="Dr Ours")
    await _doctor(db, clinics["theirs"], email="b@t.com", name="Dr Theirs")
    await db.commit()

    result = await search_doctors(db, clinics["ours"])

    assert result["status"] == "ok"
    assert [d["name"] for d in result["doctors"]] == ["Dr Ours"]


@pytest.mark.asyncio
async def test_search_never_crosses_clinics(db, clinics):
    """Even searching by the other clinic's doctor by name."""
    await _doctor(db, clinics["theirs"], email="c@t.com", name="Dr Theirs")
    await db.commit()

    result = await search_doctors(db, clinics["ours"], query="Theirs")

    assert result["status"] == "empty"
    assert result["doctors"] == []


@pytest.mark.asyncio
async def test_search_by_specialization(db, clinics):
    await _doctor(
        db, clinics["ours"], email="d@t.com", name="Dr Heart",
        specialization="Cardiology",
    )
    await _doctor(
        db, clinics["ours"], email="e@t.com", name="Dr Skin",
        specialization="Dermatology",
    )
    await db.commit()

    result = await search_doctors(db, clinics["ours"], specialization="cardiology")

    assert [d["name"] for d in result["doctors"]] == ["Dr Heart"]


@pytest.mark.asyncio
async def test_search_excludes_unapproved_and_inactive(db, clinics):
    await _doctor(
        db, clinics["ours"], email="f@t.com", name="Dr Pending",
        status=DoctorStatus.PENDING,
    )
    await _doctor(
        db, clinics["ours"], email="g@t.com", name="Dr Gone", is_active=False
    )
    await db.commit()

    result = await search_doctors(db, clinics["ours"])

    assert result["status"] == "empty"


@pytest.mark.asyncio
async def test_search_exposes_no_patient_data(db, clinics):
    await _doctor(db, clinics["ours"], email="h@t.com", name="Dr One")
    await db.commit()

    result = await search_doctors(db, clinics["ours"])

    assert set(result["doctors"][0]) == {
        "doctor_id",
        "name",
        "specialization",
        "experience_years",
        "consultation_fee",
    }


# ---------------------------------------------------------------------------
# doctor_availability
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_availability_returns_local_times(db, clinics):
    """The model must never be handed arithmetic.

    14:00 in Dhaka is 08:00 UTC; the tool returns the wall clock a clinic
    would actually say.
    """
    doctor = await _doctor(db, clinics["ours"], email="i@t.com", name="Dr Rahman")
    await _slot(db, doctor, at=datetime(2026, 3, 10, 8, 0, tzinfo=UTC))
    await db.commit()

    result = await doctor_availability(
        db, clinics["ours"], doctor_name="Rahman", on_date=date(2026, 3, 10)
    )

    assert result["status"] == "ok"
    assert result["slots"][0]["time"] == "2:00 PM"
    assert result["slots"][0]["date"] == "Tuesday 10 March"


@pytest.mark.asyncio
async def test_availability_keeps_the_exact_instant(db, clinics):
    """A display string is not an identifier; the booking button needs both."""
    doctor = await _doctor(db, clinics["ours"], email="j@t.com", name="Dr Rahman")
    await _slot(db, doctor, at=datetime(2026, 3, 10, 8, 0, tzinfo=UTC))
    await db.commit()

    result = await doctor_availability(
        db, clinics["ours"], doctor_name="Rahman", on_date=date(2026, 3, 10)
    )

    assert result["slots"][0]["starts_at"].startswith("2026-03-10T08:00")
    assert isinstance(result["slots"][0]["slot_id"], int)


@pytest.mark.asyncio
async def test_an_unknown_doctor_is_not_found(db, clinics):
    result = await doctor_availability(db, clinics["ours"], doctor_name="Nobody")

    assert result["status"] == "not_found"


@pytest.mark.asyncio
async def test_an_ambiguous_name_is_reported_not_guessed(db, clinics):
    """Two Rahmans. Answering about one of them would be confidently wrong."""
    await _doctor(db, clinics["ours"], email="k@t.com", name="Dr Rahman Ali")
    await _doctor(db, clinics["ours"], email="l@t.com", name="Dr Rahman Khan")
    await db.commit()

    result = await doctor_availability(db, clinics["ours"], doctor_name="Rahman")

    assert result["status"] == "ambiguous"
    assert len(result["candidates"]) == 2


@pytest.mark.asyncio
async def test_a_doctor_at_another_clinic_is_not_found(db, clinics):
    await _doctor(db, clinics["theirs"], email="m@t.com", name="Dr Theirs")
    await db.commit()

    result = await doctor_availability(db, clinics["ours"], doctor_name="Theirs")

    assert result["status"] == "not_found"


@pytest.mark.asyncio
async def test_a_day_with_no_slots_is_empty_not_missing(db, clinics):
    doctor = await _doctor(db, clinics["ours"], email="n@t.com", name="Dr Rahman")
    await db.commit()

    result = await doctor_availability(
        db, clinics["ours"], doctor_name="Rahman", on_date=date(2026, 3, 10)
    )

    assert result["status"] == "empty"
    assert result["doctor"]["name"] == "Dr Rahman"


# ---------------------------------------------------------------------------
# earliest_slot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_earliest_is_clinic_scoped(db, clinics):
    ours = await _doctor(db, clinics["ours"], email="o@t.com", name="Dr Ours")
    theirs = await _doctor(db, clinics["theirs"], email="p@t.com", name="Dr Theirs")

    await _slot(db, theirs, at=utc_now() + timedelta(minutes=10))
    await _slot(db, ours, at=utc_now() + timedelta(hours=2))
    await db.commit()

    result = await earliest_slot(db, clinics["ours"])

    assert [o["doctor_name"] for o in result["options"]] == ["Dr Ours"]


@pytest.mark.asyncio
async def test_earliest_returns_formatted_times(db, clinics):
    doctor = await _doctor(db, clinics["ours"], email="q@t.com", name="Dr One")
    await _slot(db, doctor, at=utc_now() + timedelta(hours=2))
    await db.commit()

    result = await earliest_slot(db, clinics["ours"])

    option = result["options"][0]
    assert "date" in option and "time" in option
    assert option["time"][-2:] in ("AM", "PM")


@pytest.mark.asyncio
async def test_nothing_free_is_empty(db, clinics):
    """A real answer the caller must relay, not a reason to look elsewhere."""
    result = await earliest_slot(db, clinics["ours"])

    assert result["status"] == "empty"
    assert result["options"] == []


# ---------------------------------------------------------------------------
# clinic_information
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clinic_information_reports_contact_and_hours(db, clinics):
    result = clinic_information(clinics["ours"])

    assert result["status"] == "ok"
    assert result["contact"]["phone"] == "+8801700000000"
    assert len(result["opening_hours"]["days"]) == 7


@pytest.mark.asyncio
async def test_unconfigured_hours_report_unknown(db, clinics):
    """Never "closed" — that would turn a gap in the data into a fact."""
    result = clinic_information(clinics["theirs"])

    assert result["status"] == "unknown"
    assert result["open_now"]["is_open"] is None


@pytest.mark.asyncio
async def test_clinic_information_exposes_no_patient_data(db, clinics):
    result = clinic_information(clinics["ours"])

    assert set(result) == {
        "tool",
        "clinic_id",
        "clinic_name",
        "status",
        "contact",
        "opening_hours",
        "holidays",
        "open_now",
    }


# ---------------------------------------------------------------------------
# Shared guarantees
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_tool_names_itself_and_its_clinic(db, clinics):
    """The caller branches on `status` and can attribute every answer."""
    results = [
        await search_doctors(db, clinics["ours"]),
        await list_specializations(db, clinics["ours"]),
        await doctor_availability(db, clinics["ours"], doctor_name="Nobody"),
        await earliest_slot(db, clinics["ours"]),
        clinic_information(clinics["ours"]),
    ]

    for result in results:
        assert result["clinic_id"] == clinics["ours"].id
        assert result["tool"]
        assert result["status"] in {"ok", "empty", "ambiguous", "not_found", "unknown"}


def test_today_is_the_clinics_today():
    """date.today() is the server's date.

    With the API in UTC and a clinic at UTC+6 the two disagree for six hours
    every day — enough for "who can see me today?" to answer for yesterday
    every evening.
    """
    clinic = Clinic(name="C", status=ClinicStatus.ACTIVE, timezone="Pacific/Kiritimati")

    # UTC+14: it is already tomorrow there for ten hours of every UTC day.
    assert clinic_today(clinic) >= datetime.now(UTC).date()


# ---------------------------------------------------------------------------
# list_specializations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_specializations_are_listed_with_counts(db, clinics):
    await _doctor(
        db, clinics["ours"], email="s1@t.com", name="Dr A",
        specialization="Cardiology",
    )
    await _doctor(
        db, clinics["ours"], email="s2@t.com", name="Dr B",
        specialization="Cardiology",
    )
    await _doctor(
        db, clinics["ours"], email="s3@t.com", name="Dr C",
        specialization="Dermatology",
    )
    await db.commit()

    result = await list_specializations(db, clinics["ours"])

    assert result["status"] == "ok"
    assert result["specializations"] == [
        {"specialization": "Cardiology", "doctor_count": 2},
        {"specialization": "Dermatology", "doctor_count": 1},
    ]


@pytest.mark.asyncio
async def test_specializations_are_clinic_scoped(db, clinics):
    """Otherwise a clinic would appear to offer a specialty it does not."""
    await _doctor(
        db, clinics["theirs"], email="s4@t.com", name="Dr Onc",
        specialization="Oncology",
    )
    await _doctor(
        db, clinics["ours"], email="s5@t.com", name="Dr Card",
        specialization="Cardiology",
    )
    await db.commit()

    result = await list_specializations(db, clinics["ours"])

    assert [s["specialization"] for s in result["specializations"]] == ["Cardiology"]


@pytest.mark.asyncio
async def test_specializations_exclude_doctors_who_are_not_practising(db, clinics):
    """A pending oncologist does not make the clinic an oncology provider."""
    await _doctor(
        db, clinics["ours"], email="s6@t.com", name="Dr Pending",
        specialization="Oncology", status=DoctorStatus.PENDING,
    )
    await _doctor(
        db, clinics["ours"], email="s7@t.com", name="Dr Inactive",
        specialization="Neurology", is_active=False,
    )
    await db.commit()

    result = await list_specializations(db, clinics["ours"])

    assert result["status"] == "empty"


@pytest.mark.asyncio
async def test_a_clinic_with_no_doctors_is_empty(db, clinics):
    result = await list_specializations(db, clinics["ours"])

    assert result["status"] == "empty"
    assert result["specializations"] == []


@pytest.mark.asyncio
async def test_the_list_is_closed_so_a_missing_specialty_reads_as_absent(
    db, clinics
):
    """The whole reason this tool exists.

    "Do you have a cancer specialist?" is answered by matching the patient's
    words against what the clinic actually has. A clinic with Cardiology and
    General Medicine offers no oncology, and the closed list is what makes
    that a fact rather than a guess.
    """
    await _doctor(
        db, clinics["ours"], email="s8@t.com", name="Dr Card",
        specialization="Cardiology",
    )
    await _doctor(
        db, clinics["ours"], email="s9@t.com", name="Dr Gen",
        specialization="General Medicine",
    )
    await db.commit()

    result = await list_specializations(db, clinics["ours"])

    offered = {s["specialization"] for s in result["specializations"]}
    assert offered == {"Cardiology", "General Medicine"}
    assert "Oncology" not in offered

"""From a classified question to a tool result.

The dispatcher is where the patient's own words meet what the clinic actually
has. Two things matter: a word only ever resolves to a specialty the clinic
really practises, and a word that resolves to nothing says so instead of
returning an empty list that reads as "we have no such doctor".
"""

from datetime import timedelta

import pytest

from app.assistant.dispatcher import (
    dispatch,
    resolve_day,
    resolve_specialization,
)
from app.assistant.router import DayReference, Intent, RoutedIntent, route
from app.assistant.tools import clinic_today
from app.models.clinic import Clinic, ClinicStatus
from app.models.doctor import Doctor, DoctorStatus
from app.models.user import User, UserRole


@pytest.fixture
async def clinic(db):
    clinic = Clinic(
        name="Dhaka Clinic",
        status=ClinicStatus.ACTIVE,
        timezone="Asia/Dhaka",
        phone="+8801700000000",
        opening_hours={"0": [{"open": "09:00", "close": "17:00"}]},
    )
    db.add(clinic)
    await db.commit()
    return clinic


async def _doctor(db, clinic, *, email, name, specialization):
    user = User(
        email=email,
        full_name=name,
        hashed_password="x",
        role=UserRole.DOCTOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    db.add(
        Doctor(
            user_id=user.id,
            clinic_id=clinic.id,
            specialization=specialization,
            experience_years=5,
            bio="Doctor",
            status=DoctorStatus.APPROVED,
        )
    )
    await db.flush()


# ---------------------------------------------------------------------------
# Resolving the patient's words
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_matching_specialty_resolves(db, clinic):
    await _doctor(
        db, clinic, email="a@t.com", name="Dr Heart", specialization="Cardiology"
    )
    await db.commit()

    assert await resolve_specialization(db, clinic, "cardiologist") == "Cardiology"


@pytest.mark.asyncio
async def test_resolution_is_case_insensitive(db, clinic):
    await _doctor(
        db, clinic, email="b@t.com", name="Dr Heart", specialization="Cardiology"
    )
    await db.commit()

    assert await resolve_specialization(db, clinic, "CARDIOLOGY") == "Cardiology"


@pytest.mark.asyncio
async def test_a_specialty_the_clinic_lacks_resolves_to_nothing(db, clinic):
    """The honest outcome, and the one that makes "no" a fact."""
    await _doctor(
        db, clinic, email="c@t.com", name="Dr Heart", specialization="Cardiology"
    )
    await db.commit()

    assert await resolve_specialization(db, clinic, "dermatology") is None


@pytest.mark.asyncio
async def test_words_that_merely_look_similar_do_not_match(db, clinic):
    """"cancer" must not resolve to "Cardiology" because both start with ca."""
    await _doctor(
        db, clinic, email="d@t.com", name="Dr Heart", specialization="Cardiology"
    )
    await db.commit()

    assert await resolve_specialization(db, clinic, "cancer") is None


@pytest.mark.asyncio
async def test_resolution_only_sees_this_clinic(db, clinic):
    other = Clinic(name="Other", status=ClinicStatus.ACTIVE, timezone="Asia/Dhaka")
    db.add(other)
    await db.flush()
    await _doctor(
        db, other, email="e@t.com", name="Dr Onc", specialization="Oncology"
    )
    await db.commit()

    assert await resolve_specialization(db, clinic, "oncology") is None


# ---------------------------------------------------------------------------
# The gap deterministic matching cannot close
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unmatched_specialty_is_reported_not_answered_as_none(db, clinic):
    """"cancer" and "Oncology" share no letters.

    Returning an empty doctor list would read as "we have no such doctor" —
    correct at a clinic without oncology, WRONG at one with it. So the gap is
    named, and the clinic's real list comes back with it.
    """
    await _doctor(
        db, clinic, email="f@t.com", name="Dr Heart", specialization="Cardiology"
    )
    await db.commit()

    result = await dispatch(db, clinic, route("Do you have a cancer specialist?"))

    assert result["status"] == "unresolved_specialization"
    assert result["requested"] == "cancer"
    assert [s["specialization"] for s in result["specializations"]] == ["Cardiology"]


# ---------------------------------------------------------------------------
# Days
# ---------------------------------------------------------------------------


def test_tomorrow_is_the_clinics_tomorrow():
    clinic = Clinic(name="C", status=ClinicStatus.ACTIVE, timezone="Asia/Dhaka")

    assert resolve_day(clinic, DayReference.TOMORROW) == clinic_today(clinic) + timedelta(
        days=1
    )


def test_no_day_means_today():
    clinic = Clinic(name="C", status=ClinicStatus.ACTIVE, timezone="Asia/Dhaka")

    assert resolve_day(clinic, None) == clinic_today(clinic)


# ---------------------------------------------------------------------------
# Each intent reaches its tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clinic_questions_reach_clinic_information(db, clinic):
    result = await dispatch(db, clinic, route("When do you close?"))

    assert result["tool"] == "clinic_information"


@pytest.mark.asyncio
async def test_specialty_questions_reach_the_list(db, clinic):
    result = await dispatch(db, clinic, route("What specialists do you have?"))

    assert result["tool"] == "list_specializations"


@pytest.mark.asyncio
async def test_availability_questions_reach_the_availability_tool(db, clinic):
    await _doctor(
        db, clinic, email="g@t.com", name="Dr Rahman", specialization="Cardiology"
    )
    await db.commit()

    result = await dispatch(db, clinic, route("Is Dr Rahman available tomorrow?"))

    assert result["tool"] == "doctor_availability"
    # The name reached the tool intact rather than carrying the question with it.
    assert result["status"] in {"ok", "empty"}


@pytest.mark.asyncio
async def test_the_soonest_reaches_the_earliest_tool(db, clinic):
    result = await dispatch(db, clinic, route("Who can see me today?"))

    assert result["tool"] == "earliest_slot"


@pytest.mark.asyncio
async def test_a_resolved_specialty_narrows_the_search(db, clinic):
    await _doctor(
        db, clinic, email="h@t.com", name="Dr Heart", specialization="Cardiology"
    )
    await _doctor(
        db, clinic, email="i@t.com", name="Dr Skin", specialization="Dermatology"
    )
    await db.commit()

    result = await dispatch(db, clinic, route("I need a cardiologist"))

    assert result["tool"] == "search_doctors"
    assert [d["name"] for d in result["doctors"]] == ["Dr Heart"]


# ---------------------------------------------------------------------------
# Declining
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_question_is_unsupported_not_an_error(db, clinic):
    """"I can't help with that" is an answer the assistant must be able to give."""
    result = await dispatch(db, clinic, RoutedIntent(Intent.UNKNOWN))

    assert result["status"] == "unsupported"
    assert result["tool"] is None


@pytest.mark.asyncio
async def test_a_symptom_question_never_reaches_a_tool(db, clinic):
    """Not diagnostic. A complaint must not be routed to a department."""
    result = await dispatch(db, clinic, route("my chest hurts"))

    assert result["status"] == "unsupported"


@pytest.mark.asyncio
async def test_every_dispatch_names_the_clinic(db, clinic):
    for question in (
        "When do you close?",
        "Who can see me today?",
        "What specialists do you have?",
        "hello",
    ):
        result = await dispatch(db, clinic, route(question))

        assert result["clinic_id"] == clinic.id

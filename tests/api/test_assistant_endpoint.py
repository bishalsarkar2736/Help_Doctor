"""The assistant over HTTP.

Public and read-only by design: everything it can say a clinic already
publishes. What has to hold at this layer is that it is still scoped to one
clinic, that it answers without the model, and that it exposes nothing about
any patient.
"""

import pytest

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
        address="12 Gulshan Ave",
        opening_hours={"0": [{"open": "09:00", "close": "17:00"}]},
    )
    db.add(clinic)
    await db.flush()

    user = User(
        email="ep-doc@test.com",
        full_name="Dr Rahman",
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
            specialization="Cardiology",
            experience_years=5,
            bio="Doctor",
            status=DoctorStatus.APPROVED,
        )
    )
    await db.commit()
    return clinic


async def _ask(client, clinic_id, question):
    return await client.post(
        "/assistant/ask",
        params={"clinic_id": clinic_id},
        json={"question": question},
    )


@pytest.mark.asyncio
async def test_anyone_can_ask(client, clinic):
    """No login. The assistant repeats what the clinic already publishes."""
    res = await _ask(client, clinic.id, "I need a cardiologist")

    assert res.status_code == 200, res.text
    assert res.json()["result"]["doctors"][0]["name"] == "Dr Rahman"


@pytest.mark.asyncio
async def test_the_answer_is_produced_without_the_model(client, clinic):
    """The default configuration has AI formatting off."""
    res = await _ask(client, clinic.id, "I need a cardiologist")

    assert res.json()["formatted_by"] == "backend"
    assert res.json()["message"]


@pytest.mark.asyncio
async def test_a_missing_clinic_is_not_found(client, clinic):
    res = await _ask(client, 999_999, "I need a cardiologist")

    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_a_suspended_clinic_is_not_answered_for(client, db):
    suspended = Clinic(
        name="Suspended", status=ClinicStatus.SUSPENDED, timezone="Asia/Dhaka"
    )
    db.add(suspended)
    await db.commit()

    res = await _ask(client, suspended.id, "I need a cardiologist")

    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_the_clinic_must_be_named(client, clinic):
    """Never "some clinic": with nothing to scope to, there is no answer."""
    res = await client.post("/assistant/ask", json={"question": "hello"})

    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_another_clinics_doctor_is_not_returned(client, db, clinic):
    other = Clinic(name="Other", status=ClinicStatus.ACTIVE, timezone="Asia/Dhaka")
    db.add(other)
    await db.flush()

    user = User(
        email="other-doc@test.com",
        full_name="Dr Elsewhere",
        hashed_password="x",
        role=UserRole.DOCTOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(
        Doctor(
            user_id=user.id,
            clinic_id=other.id,
            specialization="Cardiology",
            experience_years=5,
            bio="Doctor",
            status=DoctorStatus.APPROVED,
        )
    )
    await db.commit()

    res = await _ask(client, clinic.id, "I need a cardiologist")

    names = [d["name"] for d in res.json()["result"]["doctors"]]
    assert names == ["Dr Rahman"]


@pytest.mark.asyncio
async def test_a_medical_question_is_declined(client, clinic):
    """Not a diagnostic assistant."""
    res = await _ask(client, clinic.id, "my chest hurts, what is wrong with me")

    body = res.json()
    assert body["intent"] == "unknown"
    assert body["result"]["status"] == "unsupported"


@pytest.mark.asyncio
async def test_an_empty_question_is_rejected(client, clinic):
    res = await _ask(client, clinic.id, "")

    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_an_overlong_question_is_rejected(client, clinic):
    """The model is billed by the token; no scheduling question is an essay."""
    res = await _ask(client, clinic.id, "a" * 5000)

    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_the_reply_carries_the_data_it_was_built_from(client, clinic):
    """So the UI can render a booking action, and any claim can be checked."""
    res = await _ask(client, clinic.id, "What is your phone number?")

    body = res.json()
    assert body["result"]["contact"]["phone"] == "+8801700000000"
    assert body["intent"] == "clinic_information"


@pytest.mark.asyncio
async def test_no_patient_data_appears_in_a_reply(client, clinic):
    res = await _ask(client, clinic.id, "I need a cardiologist")

    body = res.text.lower()

    for forbidden in ("prescription", "diagnosis", "appointment_id", "patient_id"):
        assert forbidden not in body


@pytest.mark.asyncio
async def test_a_contact_question_is_answered_with_contact_details(client, clinic):
    """Not with a complaint about opening hours.

    clinic_information answers address, phone and hours together, and its
    status describes only the hours. Mapping that status straight to a sentence
    answered "what is your phone number?" with "I don't have opening hours
    recorded" — about a different question entirely.
    """
    res = await _ask(client, clinic.id, "What is your phone number?")

    message = res.json()["message"]

    assert "+8801700000000" in message
    assert not message.startswith("I don't have opening hours")


@pytest.mark.asyncio
async def test_unrecorded_hours_are_mentioned_but_do_not_take_over(client, db):
    """A clinic with no hours still answers what it does know."""
    bare = Clinic(
        name="Bare Clinic",
        status=ClinicStatus.ACTIVE,
        timezone="Asia/Dhaka",
        phone="+8801711111111",
        opening_hours={},
    )
    db.add(bare)
    await db.commit()

    res = await _ask(client, bare.id, "What is your phone number?")

    message = res.json()["message"]

    assert "+8801711111111" in message
    assert "not been recorded" in message


@pytest.mark.asyncio
async def test_hours_that_exist_are_reported_as_open_or_closed(client, clinic):
    res = await _ask(client, clinic.id, "Are you open now?")

    message = res.json()["message"]

    assert ("open now" in message) or ("closed right now" in message)

"""Auditability of prescribing through an allergy warning.

Overriding an allergy block is among the highest-risk actions a prescriber can
take. Recording that it happened is not enough — a safety review, an incident
investigation and a regulator all ask the same first question: why?

So these tests assert the CONTENT of the audit record, not merely its
existence. A test that only checked "an allergy_override event was written"
would have passed against the previous implementation, which captured no
reason at all.
"""

import pytest
from sqlalchemy import select

from app.models.appointment import AppointmentStatus
from app.models.audit_log import AuditLog
from app.models.patient import Patient
from app.services.prescription_service import MIN_ALLERGY_OVERRIDE_REASON

ALLERGEN = "Penicillin"


async def _patient_allergic_to(db, patient_user, allergen: str) -> Patient:
    patient = await db.scalar(
        select(Patient).where(Patient.user_id == patient_user.id)
    )
    if patient is None:
        patient = Patient(user_id=patient_user.id)
        db.add(patient)

    patient.allergies = allergen
    await db.commit()
    return patient


async def _latest_override(db) -> AuditLog | None:
    return await db.scalar(
        select(AuditLog)
        .where(
            AuditLog.event_type == "prescription",
            AuditLog.action == "allergy_override",
        )
        .order_by(AuditLog.id.desc())
    )


@pytest.fixture
async def allergic_appointment(
    db, auth_doctor, patient_user, appointment_factory
):
    await _patient_allergic_to(db, patient_user, ALLERGEN)
    return await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        # Prescribing requires an active consultation, not merely a booking.
        status=AppointmentStatus.IN_CONSULTATION,
    )


def _body(override=False, reason=None, medicine=ALLERGEN):
    body = {
        "notes": "test",
        "allergy_override": override,
        "items": [{"medicine_name": medicine, "dosage": "500mg"}],
    }
    if reason is not None:
        body["allergy_override_reason"] = reason
    return body


@pytest.mark.asyncio
async def test_allergy_blocks_prescription_without_override(
    client, auth_doctor, allergic_appointment
):
    """The safety net itself still works."""

    res = await client.post(
        f"/prescriptions/appointments/{allergic_appointment.id}",
        json=_body(override=False),
        headers=auth_doctor["headers"],
    )
    assert res.status_code == 400, res.text
    assert ALLERGEN.lower() in res.text.lower()


@pytest.mark.asyncio
async def test_override_without_a_reason_is_refused(
    client, auth_doctor, allergic_appointment
):
    """An override with no justification must not be possible at all."""

    res = await client.post(
        f"/prescriptions/appointments/{allergic_appointment.id}",
        json=_body(override=True),
        headers=auth_doctor["headers"],
    )
    assert res.status_code == 400, res.text
    assert "reason" in res.text.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("junk", ["x", "ok", "n/a", "   ", "fine"])
async def test_a_token_reason_is_refused(
    client, auth_doctor, allergic_appointment, junk
):
    """A trail full of 'ok' is no more auditable than no reason at all."""

    res = await client.post(
        f"/prescriptions/appointments/{allergic_appointment.id}",
        json=_body(override=True, reason=junk),
        headers=auth_doctor["headers"],
    )
    assert res.status_code == 400, res.text


@pytest.mark.asyncio
async def test_override_with_a_reason_succeeds_and_records_why(
    client, db, auth_doctor, patient_user, allergic_appointment
):
    reason = "Prior tolerance documented; benefit outweighs risk in this case."

    res = await client.post(
        f"/prescriptions/appointments/{allergic_appointment.id}",
        json=_body(override=True, reason=reason),
        headers=auth_doctor["headers"],
    )
    assert res.status_code in (200, 201), res.text

    entry = await _latest_override(db)
    assert entry is not None, "override was allowed but left no audit record"

    # The reason is the whole point of the record.
    assert entry.details["reason"] == reason
    assert entry.user_id == auth_doctor["user"].id
    assert entry.details["patient_id"] == patient_user.id
    assert ALLERGEN in entry.details["conflicts"]


@pytest.mark.asyncio
async def test_audit_captures_the_allergies_as_they_were_at_the_time(
    client, db, auth_doctor, patient_user, allergic_appointment
):
    """A later edit to the allergy list must not rewrite history.

    Without this snapshot, a reviewer reading the trail after the patient's
    record was corrected would see an override against allergies the prescriber
    was never actually warned about.
    """
    res = await client.post(
        f"/prescriptions/appointments/{allergic_appointment.id}",
        json=_body(
            override=True,
            reason="Documented prior tolerance, monitored administration.",
        ),
        headers=auth_doctor["headers"],
    )
    assert res.status_code in (200, 201), res.text

    entry = await _latest_override(db)
    assert entry.details["patient_allergies_at_time"] is not None
    assert ALLERGEN in entry.details["patient_allergies_at_time"]

    # Now change the patient's recorded allergies.
    await _patient_allergic_to(db, patient_user, "Aspirin")
    await db.refresh(entry)

    assert ALLERGEN in entry.details["patient_allergies_at_time"], (
        "the audit record changed when the patient's allergy list was edited"
    )


@pytest.mark.asyncio
async def test_no_override_event_when_there_was_no_conflict(
    client, db, auth_doctor, patient_user, appointment_factory
):
    """Setting the flag with no allergy present must not fabricate an override.

    It must also not demand a reason for something that never happened.
    """
    await _patient_allergic_to(db, patient_user, ALLERGEN)
    appointment = await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        # Prescribing requires an active consultation, not merely a booking.
        status=AppointmentStatus.IN_CONSULTATION,
    )

    before = await _latest_override(db)
    before_id = before.id if before else 0

    res = await client.post(
        f"/prescriptions/appointments/{appointment.id}",
        json=_body(override=True, medicine="Paracetamol"),
        headers=auth_doctor["headers"],
    )
    assert res.status_code in (200, 201), res.text

    after = await _latest_override(db)
    after_id = after.id if after else 0
    assert after_id == before_id, "an override was logged with no conflict"


def test_minimum_reason_length_is_meaningful():
    """Guard the constant itself — lowering it silently guts the control."""
    assert MIN_ALLERGY_OVERRIDE_REASON >= 10

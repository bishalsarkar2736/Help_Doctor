"""Allergy checking when a prescription is revised.

A revision is a new prescription document that supersedes the issued one, so it
is the same clinical decision as prescribing from scratch. It ran no allergy
check at all: a doctor could revise an issued prescription to add a recorded
allergen, and nothing blocked it or recorded it.
"""

import pytest
from sqlalchemy import select

from app.models.appointment import AppointmentStatus
from app.models.audit_log import AuditLog
from app.models.patient import Patient
from app.models.prescription import Prescription, PrescriptionStatus
from app.models.prescription_template import (
    PrescriptionTemplate,
    PrescriptionTemplateItem,
)

ALLERGEN = "Penicillin"
REASON = "Reaction was a mild rash; benefit outweighs the risk here."


async def _record_allergy(db, patient_user_id, allergen):
    patient = await db.scalar(
        select(Patient).where(Patient.user_id == patient_user_id)
    )
    if patient is None:
        patient = Patient(user_id=patient_user_id)
        db.add(patient)

    patient.allergies = allergen
    await db.commit()


@pytest.fixture
async def issued(db, auth_doctor, auth_patient, appointment_factory, prescription_factory):
    appointment = await appointment_factory(
        patient_id=auth_patient["user"].id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.COMPLETED,
    )
    prescription = await prescription_factory(
        appointment_id=appointment.id,
        doctor_id=auth_doctor["doctor"].id,
        patient_id=auth_patient["user"].id,
        status=PrescriptionStatus.ISSUED,
        revision_number=1,
        is_latest_revision=True,
    )
    return prescription


async def _revise(client, auth_doctor, prescription_id, items, **extra):
    return await client.post(
        f"/prescriptions/{prescription_id}/revisions",
        json={"notes": "revised", "items": items, **extra},
        headers=auth_doctor["headers"],
    )


def _items(*names):
    return [{"medicine_name": n, "dosage": "500mg"} for n in names]


@pytest.mark.asyncio
async def test_a_revision_is_allergy_checked(
    client, db, auth_doctor, auth_patient, issued
):
    await _record_allergy(db, auth_patient["user"].id, ALLERGEN)

    res = await _revise(client, auth_doctor, issued.id, _items("Penicillin V"))

    assert res.status_code == 400, res.text
    assert "penicillin" in res.text.lower()


@pytest.mark.asyncio
async def test_a_blocked_revision_leaves_the_original_untouched(
    client, db, auth_doctor, auth_patient, issued
):
    """The current prescription must not be superseded by a rejected revision."""
    await _record_allergy(db, auth_patient["user"].id, ALLERGEN)

    await _revise(client, auth_doctor, issued.id, _items("Penicillin V"))

    original = await db.get(Prescription, issued.id)
    await db.refresh(original)
    assert original.status == PrescriptionStatus.ISSUED
    assert original.is_latest_revision is True


@pytest.mark.asyncio
async def test_a_revision_override_is_allowed_and_audited(
    client, db, auth_doctor, auth_patient, issued
):
    await _record_allergy(db, auth_patient["user"].id, ALLERGEN)

    res = await _revise(
        client,
        auth_doctor,
        issued.id,
        _items("Penicillin V"),
        allergy_override=True,
        allergy_override_reason=REASON,
    )
    assert res.status_code == 201, res.text

    record = await db.scalar(
        select(AuditLog)
        .where(
            AuditLog.event_type == "prescription",
            AuditLog.action == "allergy_override",
        )
        .order_by(AuditLog.id.desc())
    )
    assert record is not None
    assert record.details["reason"] == REASON


@pytest.mark.asyncio
async def test_a_revision_override_without_a_reason_is_refused(
    client, db, auth_doctor, auth_patient, issued
):
    await _record_allergy(db, auth_patient["user"].id, ALLERGEN)

    res = await _revise(
        client,
        auth_doctor,
        issued.id,
        _items("Penicillin V"),
        allergy_override=True,
    )

    assert res.status_code == 400, res.text
    assert "reason" in res.text.lower()


@pytest.mark.asyncio
async def test_the_justification_carries_onto_the_new_revision(
    client, db, auth_doctor, auth_patient, issued
):
    """The revision is the record now, so it must carry its own reason."""
    await _record_allergy(db, auth_patient["user"].id, ALLERGEN)

    res = await _revise(
        client,
        auth_doctor,
        issued.id,
        _items("Penicillin V"),
        allergy_override=True,
        allergy_override_reason=REASON,
    )

    revision = await db.get(Prescription, res.json()["id"])
    await db.refresh(revision)
    assert revision.allergy_override_reason == REASON

    # "Penicillin V" is not in the catalogue, so there is no substance to
    # resolve and the snapshot falls back to the typed name. Still stable
    # enough to compare against on the next edit, which is what it is for.
    assert revision.allergy_override_substances == ["penicillin v"]


@pytest.mark.asyncio
async def test_a_clean_revision_is_unaffected(
    client, db, auth_doctor, auth_patient, issued
):
    res = await _revise(client, auth_doctor, issued.id, _items("Paracetamol"))
    assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_a_revision_template_medicine_is_checked(
    client, db, auth_doctor, auth_patient, issued
):
    """Revisions apply templates too, on the same unchecked path."""
    await _record_allergy(db, auth_patient["user"].id, ALLERGEN)

    template = PrescriptionTemplate(
        doctor_id=auth_doctor["doctor"].id,
        clinic_id=auth_doctor["doctor"].clinic_id,
        name="Course",
    )
    db.add(template)
    await db.flush()
    db.add(
        PrescriptionTemplateItem(
            template_id=template.id, medicine_name="Penicillin V"
        )
    )
    await db.commit()

    res = await _revise(
        client,
        auth_doctor,
        issued.id,
        _items("Paracetamol"),
        template_id=template.id,
    )

    assert res.status_code == 400, res.text

import pytest
from sqlalchemy import select

from app.models.patient import Patient
from app.models.appointment import AppointmentStatus
from app.models.prescription import PrescriptionStatus
from app.schemas.prescription import PrescriptionCreate, PrescriptionItemCreate
from app.services.prescription_service import create_prescription
from app.domain.prescribing.allergy import find_allergy_conflicts
from app.try_except.exceptions import BadRequestError


# ---- unit: the matcher ----

def test_find_allergy_conflicts_matches_substring():
    assert find_allergy_conflicts("Aspirin, Penicillin", ["Aspirin 75mg"]) == ["Aspirin 75mg"]


def test_find_allergy_conflicts_none_when_no_allergies():
    assert find_allergy_conflicts(None, ["Aspirin"]) == []
    assert find_allergy_conflicts("", ["Aspirin"]) == []


def test_find_allergy_conflicts_no_match():
    assert find_allergy_conflicts("Peanuts", ["Napa 500mg"]) == []


# ---- service: the prescribing block ----

async def _set_allergy(db, user_id, allergies):
    patient = await db.scalar(select(Patient).where(Patient.user_id == user_id))
    patient.allergies = allergies
    await db.flush()


@pytest.mark.asyncio
async def test_prescription_blocked_on_allergy(db, doctor, patient_user, appointment_factory):
    await _set_allergy(db, patient_user.id, "Aspirin")
    appt = await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        status=AppointmentStatus.IN_CONSULTATION,
    )
    data = PrescriptionCreate(items=[PrescriptionItemCreate(medicine_name="Aspirin 75mg")])

    with pytest.raises(BadRequestError):
        await create_prescription(db=db, doctor=doctor, appointment_id=appt.id, data=data)


@pytest.mark.asyncio
async def test_prescription_allowed_with_override(db, doctor, patient_user, appointment_factory):
    await _set_allergy(db, patient_user.id, "Aspirin")
    appt = await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        status=AppointmentStatus.IN_CONSULTATION,
    )
    data = PrescriptionCreate(
        allergy_override=True,
        items=[PrescriptionItemCreate(medicine_name="Aspirin 75mg")],
    )
    rx = await create_prescription(db=db, doctor=doctor, appointment_id=appt.id, data=data)
    assert rx.status == PrescriptionStatus.DRAFT


@pytest.mark.asyncio
async def test_prescription_ok_when_no_conflict(db, doctor, patient_user, appointment_factory):
    # patient_user has no recorded allergies by default.
    appt = await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        status=AppointmentStatus.IN_CONSULTATION,
    )
    data = PrescriptionCreate(items=[PrescriptionItemCreate(medicine_name="Napa 500mg")])
    rx = await create_prescription(db=db, doctor=doctor, appointment_id=appt.id, data=data)
    assert rx.status == PrescriptionStatus.DRAFT

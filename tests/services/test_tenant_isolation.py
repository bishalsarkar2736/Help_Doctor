import pytest
from datetime import datetime

from app.core.time import UTC
from app.models.clinic import Clinic
from app.models.user import User, UserRole
from app.models.doctor import Doctor, DoctorStatus
from app.models.appointment import Appointment
from app.models.prescription import Prescription
from app.services.appointment_service import (
    get_appointment_by_id,
)
from app.services.prescription_service import (
    get_prescription_by_id,
)
from app.try_except.exceptions import (
    ForbiddenError,
)


@pytest.mark.asyncio
async def test_doctor_cannot_access_other_clinic_appointment(
    db,
):
    # -------------------------
    # Clinic A
    # -------------------------
    clinic_a = Clinic(
        name="Clinic A",
    )

    # -------------------------
    # Clinic B
    # -------------------------
    clinic_b = Clinic(
        name="Clinic B",
    )

    db.add_all([clinic_a, clinic_b])
    await db.flush()

    # -------------------------
    # Doctor A
    # -------------------------
    doctor_user_a = User(
        email="doctora@test.com",
        hashed_password="hash",
        role=UserRole.DOCTOR,
    )

    # -------------------------
    # Doctor B
    # -------------------------
    doctor_user_b = User(
        email="doctorb@test.com",
        hashed_password="hash",
        role=UserRole.DOCTOR,
    )

    # Patient
    patient_user = User(
        email="patient@test.com",
        hashed_password="hash",
        role=UserRole.PATIENT,
    )

    db.add_all(
        [
            doctor_user_a,
            doctor_user_b,
            patient_user,
        ]
    )
    await db.flush()

    doctor_a = Doctor(
        user_id=doctor_user_a.id,
        clinic_id=clinic_a.id,
        specialization="Cardiology",
        experience_years=5,
        bio="Doctor A",
        status=DoctorStatus.APPROVED,
    )

    doctor_b = Doctor(
        user_id=doctor_user_b.id,
        clinic_id=clinic_b.id,
        specialization="Medicine",
        experience_years=5,
        bio="Doctor B",
        status=DoctorStatus.APPROVED,
    )

    db.add_all([doctor_a, doctor_b])
    await db.flush()

    appointment = Appointment(
        patient_id=patient_user.id,
        doctor_id=doctor_a.id,
        clinic_id=clinic_a.id,
        scheduled_at=datetime.now(UTC),
        status="CONFIRMED",
    )

    db.add(appointment)
    await db.commit()

    with pytest.raises(
        ForbiddenError,
        match="Cross-clinic access denied",
    ):
        await get_appointment_by_id(
            db=db,
            appointment_id=appointment.id,
            user=doctor_user_b,
        )


@pytest.mark.asyncio
async def test_doctor_cannot_access_other_clinic_prescription(
    db,
):
    # -------------------------
    # Clinics
    # -------------------------
    clinic_a = Clinic(
        name="Clinic A",
    )

    clinic_b = Clinic(
        name="Clinic B",
    )

    db.add_all([clinic_a, clinic_b])
    await db.flush()

    # -------------------------
    # Users
    # -------------------------
    doctor_user_a = User(
        email="doctora2@test.com",
        hashed_password="hash",
        role=UserRole.DOCTOR,
    )

    doctor_user_b = User(
        email="doctorb2@test.com",
        hashed_password="hash",
        role=UserRole.DOCTOR,
    )

    patient_user = User(
        email="patient2@test.com",
        hashed_password="hash",
        role=UserRole.PATIENT,
    )

    db.add_all(
        [
            doctor_user_a,
            doctor_user_b,
            patient_user,
        ]
    )

    await db.flush()

    doctor_a = Doctor(
        user_id=doctor_user_a.id,
        clinic_id=clinic_a.id,
        specialization="Cardiology",
        experience_years=5,
        bio="Doctor A",
        status=DoctorStatus.APPROVED,
    )

    doctor_b = Doctor(
        user_id=doctor_user_b.id,
        clinic_id=clinic_b.id,
        specialization="Medicine",
        experience_years=5,
        bio="Doctor B",
        status=DoctorStatus.APPROVED,
    )

    db.add_all([doctor_a, doctor_b])
    await db.flush()

    appointment = Appointment(
        patient_id=patient_user.id,
        doctor_id=doctor_a.id,
        clinic_id=clinic_a.id,
        scheduled_at=datetime.now(UTC),
        status="CONFIRMED",
    )

    db.add(appointment)
    await db.flush()

    prescription = Prescription(
        appointment_id=appointment.id,
        doctor_id=doctor_a.id,
        patient_id=patient_user.id,
        clinic_id=clinic_a.id,
    )

    db.add(prescription)

    await db.commit()

    with pytest.raises(
        ForbiddenError,
        match="Cross-clinic access denied",
    ):
        await get_prescription_by_id(
            db=db,
            prescription_id=prescription.id,
            user=doctor_user_b,
        )
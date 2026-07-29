import pytest
from datetime import datetime

from app.core.time import UTC
from app.models.user import User, UserRole
from app.models.doctor import Doctor, DoctorStatus
from app.models.appointment import Appointment
from app.services.payment_service import create_payment
from app.try_except.exceptions import NotFoundError


@pytest.mark.asyncio
async def test_patient_cannot_create_payment_for_other_patient_appointment(
    db,
    default_clinic,
):
    # -----------------------------
    # Users
    # -----------------------------
    patient_a = User(
        email="patient_a@test.com",
        hashed_password="hash",
        role=UserRole.PATIENT,
    )

    patient_b = User(
        email="patient_b@test.com",
        hashed_password="hash",
        role=UserRole.PATIENT,
    )

    doctor_user = User(
        email="doctor@test.com",
        hashed_password="hash",
        role=UserRole.DOCTOR,
    )

    db.add_all(
        [
            patient_a,
            patient_b,
            doctor_user,
        ]
    )

    await db.flush()

    # -----------------------------
    # Doctor
    # -----------------------------
    doctor = Doctor(
        user_id=doctor_user.id,
        clinic_id=default_clinic.id,
        specialization="Cardiology",
        experience_years=5,
        bio="Cardiology specialist",
        status=DoctorStatus.APPROVED,
    )

    db.add(doctor)
    await db.flush()

    # -----------------------------
    # Appointment belongs to Patient A
    # -----------------------------
    appointment = Appointment(
        patient_id=patient_a.id,
        doctor_id=doctor.id,
        clinic_id=default_clinic.id,
        scheduled_at=datetime.now(UTC),
        status="CONFIRMED",
    )

    db.add(appointment)
    await db.commit()

    # -----------------------------
    # Patient B attempts payment
    # -----------------------------
    with pytest.raises(
        NotFoundError,
        match="Appointment not found",
    ):
        await create_payment(
            db=db,
            appointment_id=appointment.id,
            patient_id=patient_b.id,
            method="bkash",
        )
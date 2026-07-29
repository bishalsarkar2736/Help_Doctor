from datetime import date
import pytest
from datetime import datetime

from app.core.time import UTC
from app.models.user import User, UserRole
from app.models.doctor import Doctor, DoctorStatus
from app.models.patient import Patient
from app.models.appointment import Appointment
from app.models.payment import Payment


@pytest.mark.asyncio
async def test_retry_payment_allowed(
    db,
    default_clinic,
):

    # -----------------------------
    # Create users
    # -----------------------------
    patient_user = User(
        email="patient@test.com",
        hashed_password="hash",
        role=UserRole.PATIENT,
    )

    doctor_user = User(
        email="doctor@test.com",
        hashed_password="hash",
        role=UserRole.DOCTOR,
    )

    db.add_all([patient_user, doctor_user])
    await db.flush()

    # -----------------------------
    # Create doctor
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
    # Create patient
    # -----------------------------
    patient = Patient(
        user_id=patient_user.id,
        phone="01700000000",
        address="Rangpur",
        date_of_birth=date(1995, 1, 1),
        gender="MALE",
    )

    db.add(patient)
    await db.flush()

    # -----------------------------
    # Create appointment
    # -----------------------------
    appointment = Appointment(
        patient_id=patient.user_id,
        doctor_id=doctor.id,
        clinic_id=default_clinic.id,
        scheduled_at=datetime.now(UTC),
        status="CONFIRMED",
    )

    db.add(appointment)
    await db.flush()

    # -----------------------------
    # Failed payment
    # -----------------------------
    failed_payment = Payment(
        appointment_id=appointment.id,
        patient_id=patient_user.id,
        clinic_id=default_clinic.id,
        amount=500,
        method="bkash",
        status="FAILED",
    )

    db.add(failed_payment)
    await db.commit()

    # -----------------------------
    # Retry payment
    # -----------------------------
    retry_payment = Payment(
        appointment_id=appointment.id,
        patient_id=patient_user.id,
        clinic_id=default_clinic.id,
        amount=500,
        method="bkash",
        status="PENDING",
    )

    db.add(retry_payment)
    await db.commit()
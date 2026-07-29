from datetime import date
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from app.core.time import UTC
from app.models.appointment import Appointment
from app.models.doctor import Doctor, DoctorStatus
from app.models.enums.payment_status import PaymentStatus
from app.models.patient import Patient
from app.models.payment import Payment
from app.models.user import User, UserRole


async def create_success_payment(
    db,
    default_clinic,
):
    patient_user = User(
        email=f"patient-{uuid4().hex}@test.com",
        hashed_password="hash",
        role=UserRole.PATIENT,
    )

    doctor_user = User(
        email=f"doctor-{uuid4().hex}@test.com",
        hashed_password="hash",
        role=UserRole.DOCTOR,
    )

    db.add_all([patient_user, doctor_user])
    await db.flush()

    doctor = Doctor(
        user_id=doctor_user.id,
        clinic_id=default_clinic.id,
        specialization="Medicine",
        experience_years=5,
        bio="Doctor",
        status=DoctorStatus.APPROVED,
    )

    db.add(doctor)
    await db.flush()

    patient = Patient(
        user_id=patient_user.id,
        phone="01700000000",
        address="Dhaka",
        date_of_birth=date(1995, 1, 1),
        gender="MALE",
    )

    db.add(patient)
    await db.flush()

    appointment = Appointment(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        clinic_id=default_clinic.id,
        consultation_fee=Decimal("500"),
        scheduled_at=datetime.now(UTC),
    )

    db.add(appointment)
    await db.flush()

    payment = Payment(
        appointment_id=appointment.id,
        patient_id=patient_user.id,
        clinic_id=default_clinic.id,
        amount=Decimal("500"),
        method="bkash",
        status=PaymentStatus.SUCCESS,
        transaction_id=f"trx-{uuid4().hex}",
        gateway_payment_id=f"gw-{uuid4().hex}",
    )

    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    return payment
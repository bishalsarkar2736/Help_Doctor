from decimal import Decimal
from datetime import datetime

import pytest

from app.core.time import UTC
from app.models.user import User, UserRole
from app.models.doctor import Doctor, DoctorStatus
from app.models.appointment import Appointment
from app.models.payment import Payment
from app.models.enums.payment_status import PaymentStatus
from app.services.payment_service import (
    mark_payment_success,
)
from app.try_except.exceptions import (
    BadRequestError,
)


async def create_payment(
    db,
    default_clinic,
    *,
    email_prefix: str,
    gateway_payment_id: str,
    status: PaymentStatus = PaymentStatus.PENDING,
    transaction_id: str | None = None,
):
    patient = User(
        email=f"{email_prefix}@patient.com",
        hashed_password="hash",
        role=UserRole.PATIENT,
    )

    doctor_user = User(
        email=f"{email_prefix}@doctor.com",
        hashed_password="hash",
        role=UserRole.DOCTOR,
    )

    db.add_all([patient, doctor_user])
    await db.flush()

    doctor = Doctor(
        user_id=doctor_user.id,
        clinic_id=default_clinic.id,
        specialization="Cardiology",
        experience_years=5,
        bio="test",
        status=DoctorStatus.APPROVED,
    )

    db.add(doctor)
    await db.flush()

    appointment = Appointment(
        patient_id=patient.id,
        doctor_id=doctor.id,
        clinic_id=default_clinic.id,
        consultation_fee=Decimal("500.00"),
        scheduled_at=datetime.now(UTC),
    )

    db.add(appointment)
    await db.flush()

    payment = Payment(
        appointment_id=appointment.id,
        patient_id=patient.id,
        clinic_id=default_clinic.id,
        amount=Decimal("500.00"),
        method="bkash",
        status=status,
        gateway_payment_id=gateway_payment_id,
        transaction_id=transaction_id,
    )

    db.add(payment)
    await db.commit()

    return payment


@pytest.mark.asyncio
async def test_mark_payment_success_duplicate_transaction_id(
    db,
    default_clinic,
):
    # Existing successful payment
    await create_payment(
        db,
        default_clinic,
        email_prefix="existing",
        gateway_payment_id="gw-existing",
        status=PaymentStatus.SUCCESS,
        transaction_id="trx_001",
    )

    # Pending payment trying to reuse trx_001
    pending_payment = await create_payment(
        db,
        default_clinic,
        email_prefix="pending",
        gateway_payment_id="gw-pending",
    )

    with pytest.raises(
        BadRequestError,
        match="Transaction already processed",
    ):
        await mark_payment_success(
            db=db,
            transaction_id="trx_001",
            gateway_payment_id=(
                pending_payment.gateway_payment_id
            ),
            paid_amount=Decimal("500.00"),
        )
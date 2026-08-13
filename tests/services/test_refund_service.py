from datetime import date
from decimal import Decimal
from datetime import datetime
from unittest.mock import AsyncMock, patch
from sqlalchemy import select
import pytest
from app.models.clinic import Clinic
from app.core.time import UTC
from app.models.appointment import Appointment
from app.models.doctor import Doctor, DoctorStatus
from app.models.enums.payment_status import PaymentStatus
from app.models.patient import Patient
from app.models.payment import Payment
from app.models.user import User, UserRole
from app.services.payment_refund_service import refund_payment
from app.try_except.exceptions import (
    NotFoundError,
    BadRequestError,
    ForbiddenError,
)
from app.models.payment_audit_log import PaymentAuditLog
from app.models.outbox_event import OutboxEvent




async def create_success_payment(
    db,
    default_clinic,
):
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
        transaction_id="trx-001",
        gateway_payment_id="gw-001",
    )

    db.add(payment)
    await db.commit()

    return payment, doctor_user


def mock_bkash_refund(refund_transaction_id="bkash-refund-txn-001"):
    return patch(
        "app.services.payment_refund_service.BkashService.refund_payment",
        new=AsyncMock(
            return_value={
                "transactionStatus": "Completed",
                "refundTransactionId": refund_transaction_id,
            }
        ),
    )


@pytest.mark.asyncio
async def test_refund_payment_not_found(
    db,
    default_clinic,
):
    _, doctor = await create_success_payment(
        db,
        default_clinic,
    )

    with pytest.raises(NotFoundError):
        await refund_payment(
            db=db,
            payment_id=999999,
            refunded_by=doctor,
            amount=Decimal("100"),
            reason="Patient requested refund",
        )



@pytest.mark.asyncio
async def test_refund_requires_success_payment(
    db,
    default_clinic,
):
    payment, doctor_user = await create_success_payment(
        db,
        default_clinic,
    )

    # Payment is no longer successful
    payment.status = PaymentStatus.PENDING
    await db.commit()

    with pytest.raises(BadRequestError) as exc:
        await refund_payment(
            db=db,
            payment_id=payment.id,
            refunded_by=doctor_user,
            amount=Decimal("100"),
            reason="Patient requested refund",
        )

    assert str(exc.value) == (
        "Only successful payments can be refunded"
    )


@pytest.mark.asyncio
async def test_refund_requires_positive_amount(
    db,
    default_clinic,
):
    payment, doctor_user = await create_success_payment(
        db,
        default_clinic,
    )

    with pytest.raises(BadRequestError) as exc:
        await refund_payment(
            db=db,
            payment_id=payment.id,
            refunded_by=doctor_user,
            amount=Decimal("0"),
            reason="Patient requested refund",
        )

    assert str(exc.value) == (
        "Refund amount must be greater than zero"
    )


@pytest.mark.asyncio
async def test_refund_amount_exceeds_payment(
    db,
    default_clinic,
):
    payment, doctor_user = await create_success_payment(
        db,
        default_clinic,
    )

    with pytest.raises(BadRequestError) as exc:
        await refund_payment(
            db=db,
            payment_id=payment.id,
            refunded_by=doctor_user,
            amount=Decimal("1000"),
            reason="Patient requested refund",
        )

    assert str(exc.value) == (
        "Refund amount exceeds payment amount"
    )


@pytest.mark.asyncio
async def test_refund_already_refunded(
    db,
    default_clinic,
):
    payment, doctor_user = await create_success_payment(
        db,
        default_clinic,
    )

    payment.status = PaymentStatus.REFUNDED
    await db.commit()

    with pytest.raises(BadRequestError) as exc:
        await refund_payment(
            db=db,
            payment_id=payment.id,
            refunded_by=doctor_user,
            amount=Decimal("100"),
            reason="Patient requested refund",
        )

    assert str(exc.value) == (
        "Payment has already been refunded"
    )


@pytest.mark.asyncio
async def test_refund_requires_same_clinic(
    db,
    default_clinic,
):
    payment, doctor_user = await create_success_payment(
        db,
        default_clinic,
    )

    # ---------------------------------
    # Create another clinic
    # ---------------------------------
    another_clinic = Clinic(
        name="Another Clinic",
        address="Dhaka",
        phone="01800000000",
        email="another@test.com",
        website="https://another.com",
        primary_color="#FF0000",
    )

    db.add(another_clinic)
    await db.flush()

    # ---------------------------------
    # Move doctor to another clinic
    # ---------------------------------
    doctor = await db.scalar(
        select(Doctor).where(
            Doctor.user_id == doctor_user.id
        )
    )

    doctor.clinic_id = another_clinic.id

    await db.commit()

    # ---------------------------------
    # Refund should fail
    # ---------------------------------
    with pytest.raises(ForbiddenError) as exc:
        await refund_payment(
            db=db,
            payment_id=payment.id,
            refunded_by=doctor_user,
            amount=Decimal("100"),
            reason="Patient requested refund",
        )

    assert str(exc.value) == (
        "Payment does not belong to your clinic"
    )

@pytest.mark.asyncio
async def test_refund_requires_admin_or_doctor(
    db,
    default_clinic,
):
    payment, _ = await create_success_payment(
        db,
        default_clinic,
    )

    receptionist = User(
        email="reception@test.com",
        hashed_password="hash",
        role=UserRole.RECEPTIONIST,
    )

    db.add(receptionist)
    await db.commit()

    with pytest.raises(ForbiddenError) as exc:
        await refund_payment(
            db=db,
            payment_id=payment.id,
            refunded_by=receptionist,
            amount=Decimal("100"),
            reason="Patient requested refund",
        )

    assert str(exc.value) == (
        "You do not have permission to refund payments"
    )

@pytest.mark.asyncio
async def test_refund_requires_reason(
    db,
    default_clinic,
):
    payment, doctor_user = await create_success_payment(
        db,
        default_clinic,
    )

    with pytest.raises(BadRequestError) as exc:
        await refund_payment(
            db=db,
            payment_id=payment.id,
            refunded_by=doctor_user,
            amount=Decimal("100"),
            reason="",
        )

    assert str(exc.value) == (
        "Refund reason is required"
    )


@pytest.mark.asyncio
async def test_refund_marks_payment_refunded(
    db,
    default_clinic,
):
    payment, doctor_user = await create_success_payment(
        db,
        default_clinic,
    )

    with mock_bkash_refund():
        refunded_payment = await refund_payment(
            db=db,
            payment_id=payment.id,
            refunded_by=doctor_user,
            amount=Decimal("100"),
            reason="Patient requested refund",
        )

    await db.refresh(refunded_payment)

    assert refunded_payment.status == PaymentStatus.REFUNDED



@pytest.mark.asyncio
async def test_refund_sets_refunded_amount(
    db,
    default_clinic,
):
    payment, doctor_user = await create_success_payment(
        db,
        default_clinic,
    )

    with mock_bkash_refund():
        refunded_payment = await refund_payment(
            db=db,
            payment_id=payment.id,
            refunded_by=doctor_user,
            amount=Decimal("125"),
            reason="Patient requested refund",
        )

    await db.refresh(refunded_payment)

    assert refunded_payment.refunded_amount == Decimal("125")


@pytest.mark.asyncio
async def test_refund_sets_refunded_at(
    db,
    default_clinic,
):
    payment, doctor_user = await create_success_payment(
        db,
        default_clinic,
    )

    with mock_bkash_refund():
        refunded_payment = await refund_payment(
            db=db,
            payment_id=payment.id,
            refunded_by=doctor_user,
            amount=Decimal("100"),
            reason="Patient requested refund",
        )

    await db.refresh(refunded_payment)

    assert refunded_payment.refunded_at is not None



@pytest.mark.asyncio
async def test_refund_generates_refund_transaction_id(
    db,
    default_clinic,
):
    payment, doctor_user = await create_success_payment(
        db,
        default_clinic,
    )

    with mock_bkash_refund(refund_transaction_id="bkash-refund-abc123"):
        refunded_payment = await refund_payment(
            db=db,
            payment_id=payment.id,
            refunded_by=doctor_user,
            amount=Decimal("100"),
            reason="Patient requested refund",
        )

    await db.refresh(refunded_payment)

    assert refunded_payment.refund_transaction_id is not None

    assert refunded_payment.refund_transaction_id == (
        "bkash-refund-abc123"
    )


@pytest.mark.asyncio
async def test_refund_creates_audit_log(
    db,
    default_clinic,
):
    payment, doctor_user = await create_success_payment(
        db,
        default_clinic,
    )

    with mock_bkash_refund():
        refunded_payment = await refund_payment(
            db=db,
            payment_id=payment.id,
            refunded_by=doctor_user,
            amount=Decimal("100"),
            reason="Patient requested refund",
        )

    await db.commit()

    result = await db.execute(
        select(PaymentAuditLog).where(
            PaymentAuditLog.payment_id == payment.id
        )
    )

    audit_logs = result.scalars().all()

    assert len(audit_logs) == 1

    audit = audit_logs[0]

    assert audit.payment_id == payment.id

    assert audit.gateway == payment.method

    assert audit.event_type == "payment_refunded"

    assert (
        audit.payload["refund_transaction_id"]
        == refunded_payment.refund_transaction_id
    )

    assert (
        audit.payload["refunded_amount"]
        == str(refunded_payment.refunded_amount)
    )

    assert (
        audit.payload["reason"]
        == "Patient requested refund"
    )

    assert (
        audit.payload["refunded_by"]
        == doctor_user.id
    )


@pytest.mark.asyncio
async def test_refund_publishes_event(
    db,
    default_clinic,
):
    payment, doctor_user = await create_success_payment(
        db,
        default_clinic,
    )

    with mock_bkash_refund():
        refunded_payment = await refund_payment(
            db=db,
            payment_id=payment.id,
            refunded_by=doctor_user,
            amount=Decimal("100"),
            reason="Patient requested refund",
        )

    result = await db.execute(
        select(OutboxEvent)
        .where(
            OutboxEvent.event_type
            == "PAYMENT_REFUNDED"
        )
    )

    events = result.scalars().all()

    assert len(events) == 1

    event = events[0]

    assert event.event_type == "PAYMENT_REFUNDED"

    payload = event.payload

    # The PATIENT, not whoever issued the refund.
    #
    # This asserted doctor_user.id, which is what the service used to send. Every
    # other event in this system uses user_id for the RECIPIENT, and the
    # notification reads "Your payment of X has been refunded" — addressed to
    # the refunder it told an administrator about their own money while the
    # patient heard nothing.
    assert payload["user_id"] == payment.patient_id

    # Attribution is not lost by moving the recipient: actor still records who
    # performed the refund.
    assert payload["actor"]["id"] == doctor_user.id

    assert (
        payload["appointment_id"]
        == payment.appointment_id
    )

    assert payload["payment_id"] == payment.id

    assert (
        payload["refund_transaction_id"]
        == refunded_payment.refund_transaction_id
    )

    assert (
        payload["refunded_amount"]
        == "100"
    )

    assert payload["actor"]["id"] == doctor_user.id
    assert (
        payload["actor"]["role"]
        == UserRole.DOCTOR.value
    )

    assert payload["occurred_at"] is not None


# ---------------------------------------------------------------------------
# ADMIN, across clinics
#
# test_refund_requires_same_clinic above proves the boundary for a DOCTOR, by
# reassigning one to another clinic. validate_refund_access checks the doctor's
# clinic against the payment's — but returns unconditionally for ADMIN, before
# any comparison, under the comment "Admin can refund any payment".
#
# ADMIN is clinic-bound in this system (resolve_clinic_id raises "Admin not
# assigned to clinic"; the platform role is SUPER_ADMIN), so "any payment"
# spans tenants. This is a write, and it moves money through the live gateway.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_cannot_refund_another_clinics_payment(
    db,
    default_clinic,
    other_clinic_admin,
):
    """Clinic B's admin, against a payment that belongs to clinic A.

    The gateway is mocked so that a failure here reports the real defect —
    the refund being permitted — rather than a network error from the refund
    proceeding to call bKash for real.
    """

    payment, _ = await create_success_payment(
        db,
        default_clinic,
    )

    with mock_bkash_refund() as gateway:

        with pytest.raises(ForbiddenError):
            await refund_payment(
                db=db,
                payment_id=payment.id,
                refunded_by=other_clinic_admin["user"],
                amount=Decimal("100"),
                reason="Patient requested refund",
            )

        # Authorization must fail before any money moves.
        gateway.assert_not_awaited()

    await db.refresh(payment)

    assert payment.status == PaymentStatus.SUCCESS


@pytest.mark.asyncio
async def test_the_payments_own_clinic_admin_can_still_refund(
    db,
    default_clinic,
    auth_admin,
):
    """The paired allow-case: admins must keep the ability to refund inside
    their own clinic, so the denial above cannot be satisfied by breaking
    admin refunds altogether."""

    payment, _ = await create_success_payment(
        db,
        default_clinic,
    )

    with mock_bkash_refund():
        refunded_payment = await refund_payment(
            db=db,
            payment_id=payment.id,
            refunded_by=auth_admin["user"],
            amount=Decimal("100"),
            reason="Patient requested refund",
        )

    await db.refresh(refunded_payment)

    assert refunded_payment.status == PaymentStatus.REFUNDED
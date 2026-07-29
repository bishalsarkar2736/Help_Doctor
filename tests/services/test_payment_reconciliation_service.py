
from decimal import Decimal
from datetime import datetime, timedelta

import pytest


from app.core.time import UTC
from app.models.payment import Payment
from app.models.enums.payment_status import PaymentStatus
from app.services.payment_reconciliation_service import (
    reconcile_pending_payments,
)
from app.models.user import User, UserRole
from app.models.doctor import Doctor, DoctorStatus
from app.models.appointment import Appointment



async def create_pending_payment(
    db,
    default_clinic,
    gateway_payment_id: str,
    *,
    amount: str = "500.00",
):
    patient = User(
        email=f"{gateway_payment_id}@patient.com",
        hashed_password="hash",
        role=UserRole.PATIENT,
    )

    doctor_user = User(
        email=f"{gateway_payment_id}@doctor.com",
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
        consultation_fee=Decimal(amount),
        scheduled_at=datetime.now(UTC),
    )

    db.add(appointment)
    await db.flush()

    payment = Payment(
        appointment_id=appointment.id,
        patient_id=patient.id,
        clinic_id=default_clinic.id,
        amount=Decimal(amount),
        method="bkash",
        status=PaymentStatus.PENDING,
        gateway_payment_id=gateway_payment_id,
    )

    db.add(payment)
    await db.commit()

    return payment



@pytest.mark.asyncio
async def test_reconcile_completed_payment_marks_success(
    db,
    default_clinic,
    monkeypatch,
):
    
    payment = await create_pending_payment(
        db,
        default_clinic,
        "gw-success",
    )

    called = {}

    class FakeBkash:
        async def query_payment(self, gateway_payment_id):
            return {
                "transactionStatus": "Completed",
                "amount": "500.00",
                "trxID": "TRX123",
            }

    async def fake_mark_payment_success(**kwargs):
        called["success"] = kwargs
        return payment

    async def fake_create_audit_log(**kwargs):
        called["audit"] = kwargs

    monkeypatch.setattr(
        "app.services.payment_reconciliation_service.BkashService",
        FakeBkash,
    )

    monkeypatch.setattr(
        "app.services.payment_reconciliation_service.mark_payment_success",
        fake_mark_payment_success,
    )

    monkeypatch.setattr(
        "app.services.payment_reconciliation_service.create_payment_audit_log",
        fake_create_audit_log,
    )

    await reconcile_pending_payments(db=db)

    assert called["success"]["gateway_payment_id"] == "gw-success"
    assert called["success"]["transaction_id"] == "TRX123"

    assert (
        called["audit"]["event_type"]
        == "reconciliation_success"
    )


@pytest.mark.asyncio
async def test_reconcile_failed_payment_marks_failed(
    db,
    default_clinic,
    monkeypatch,
):
    payment = await create_pending_payment(
        db,
        default_clinic,
        "gw-failed",
    )

    called = {}

    class FakeBkash:
        async def query_payment(self, gateway_payment_id):
            return {
                "transactionStatus": "Failed",
            }

    async def fake_mark_payment_failed(**kwargs):
        called["failed"] = kwargs
        return payment

    async def fake_create_audit_log(**kwargs):
        called["audit"] = kwargs

    monkeypatch.setattr(
        "app.services.payment_reconciliation_service.BkashService",
        FakeBkash,
    )

    monkeypatch.setattr(
        "app.services.payment_reconciliation_service.mark_payment_failed",
        fake_mark_payment_failed,
    )

    monkeypatch.setattr(
        "app.services.payment_reconciliation_service.create_payment_audit_log",
        fake_create_audit_log,
    )

    await reconcile_pending_payments(db=db)

    assert (
        called["failed"]["gateway_payment_id"]
        == "gw-failed"
    )

    assert (
        called["audit"]["event_type"]
        == "reconciliation_failed"
    )


@pytest.mark.asyncio
async def test_reconcile_amount_mismatch_does_not_mark_success(
    db,
    default_clinic,
    monkeypatch,
):
    await create_pending_payment(
        db,
        default_clinic,
        "gw-mismatch",
    )

    called = {
        "success": False,
        "audit": False,
    }

    class FakeBkash:
        async def query_payment(self, gateway_payment_id):
            return {
                "transactionStatus": "Completed",
                "amount": "999.00",
                "trxID": "TRX999",
            }

    async def fake_mark_payment_success(**kwargs):
        called["success"] = True

    async def fake_create_audit_log(**kwargs):
        called["audit"] = kwargs

    monkeypatch.setattr(
        "app.services.payment_reconciliation_service.BkashService",
        FakeBkash,
    )

    monkeypatch.setattr(
        "app.services.payment_reconciliation_service.mark_payment_success",
        fake_mark_payment_success,
    )

    monkeypatch.setattr(
        "app.services.payment_reconciliation_service.create_payment_audit_log",
        fake_create_audit_log,
    )

    await reconcile_pending_payments(db=db)

    assert called["success"] is False

    assert (
        called["audit"]["event_type"]
        == "reconciliation_amount_mismatch"
    )


@pytest.mark.asyncio
async def test_reconcile_ignores_unknown_status(
    db,
    default_clinic,
    monkeypatch,
):
    await create_pending_payment(
        db,
        default_clinic,
        "gw-processing",
    )

    called = False

    class FakeBkash:
        async def query_payment(self, gateway_payment_id):
            return {
                "transactionStatus": "Processing",
            }

    async def fake_mark_payment_success(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        "app.services.payment_reconciliation_service.BkashService",
        FakeBkash,
    )

    monkeypatch.setattr(
        "app.services.payment_reconciliation_service.mark_payment_success",
        fake_mark_payment_success,
    )

    await reconcile_pending_payments(db=db)

    assert called is False


@pytest.mark.asyncio
async def test_reconcile_skips_old_pending_payments(
    db,
    default_clinic,
    monkeypatch,
):
    old_payment = await create_pending_payment(
        db,
        default_clinic,
        "gw-old",
    )

    await db.refresh(old_payment)

    old_payment.created_at = (
        datetime.now(UTC) - timedelta(days=10)
    )

    await db.flush()
    await db.commit()

    called = False

    class FakeBkash:
        async def query_payment(self, gateway_payment_id):
            nonlocal called
            called = True
            return {}

    monkeypatch.setattr(
        "app.services.payment_reconciliation_service.BkashService",
        FakeBkash,
    )

    await reconcile_pending_payments(db=db)

    assert called is False
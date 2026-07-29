from datetime import date

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient
from datetime import datetime
from sqlalchemy import select,text,func

from app.core.time import UTC
from app.models.user import User, UserRole
from app.models.doctor import Doctor, DoctorStatus
from app.models.patient import Patient
from app.models.appointment import Appointment
from app.models.payment import Payment
from app.models.payment_audit_log import PaymentAuditLog
from datetime import timedelta
from sqlalchemy.dialects.postgresql import Range
from app.core.constants import APPOINTMENT_DURATION_MINUTES


@pytest.mark.asyncio
async def test_bkash_webhook_success(
    client: AsyncClient, 
    db,
    default_clinic,
):

    result = await db.execute(text("SELECT current_database()"))
    print("CURRENT DB:", result.scalar())

    result = await db.execute(text("SHOW search_path"))
    print("SEARCH PATH:", result.scalar())

    result = await db.execute(text("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_name = 'payments'
    """))
    print("PAYMENTS TABLE:", result.fetchall())

    # -----------------------------
    # Create users
    # -----------------------------
    patient_user = User(
        email="patient@test.com",
        hashed_password="testhash",
        role=UserRole.PATIENT,
    )

    doctor_user = User(
        email="doctor@test.com",
        hashed_password="testhash",
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
    start = datetime.now(UTC)

    appointment = Appointment(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        clinic_id=default_clinic.id,
        scheduled_at=start,
        status="CONFIRMED",
        time_range=Range(
            start,
            start + timedelta(minutes=APPOINTMENT_DURATION_MINUTES),
        )
    )
    db.add(appointment)
    await db.flush()

    # -----------------------------
    # Create pending payment
    # -----------------------------
    payment = Payment(
        appointment_id=appointment.id,
        patient_id=patient_user.id,
        clinic_id=default_clinic.id,
        amount=500,
        method="bkash",
        status="PENDING",
        gateway_payment_id="test123",
    )
    db.add(payment)
    await db.commit()

    # -----------------------------
    # Webhook payload
    # -----------------------------
    payload = {"paymentID": "test123"}

    mock_response = {
         "transactionStatus": "Completed",
        "trxID": "trx_001",
        "amount": "500",
    }

    # -----------------------------
    # Mock bKash API
    # -----------------------------
    with patch(
        "app.services.payment_webhook_service.BkashService.execute_payment",
        new=AsyncMock(return_value=mock_response),
    ):
        response = await client.post("/payments/webhook/bkash", json=payload)

    # -----------------------------
    # Response check
    # -----------------------------
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    # -----------------------------
    # Payment should be updated
    # -----------------------------
    result = await db.execute(select(Payment))
    updated_payment = result.scalar_one()

    assert updated_payment.status == "SUCCESS"
    assert updated_payment.transaction_id == "trx_001"

    # -----------------------------
    # Audit log should be created
    # -----------------------------
    result = await db.execute(select(PaymentAuditLog))
    audit_log = result.scalar_one()

    assert audit_log.payment_id == payment.id
    assert audit_log.gateway == "bkash"



@pytest.mark.asyncio
async def test_bkash_webhook_is_idempotent(
    client: AsyncClient,
    db,
    default_clinic,
):
    # -----------------------------
    # Create users
    # -----------------------------
    patient_user = User(
        email="patient@test.com",
        hashed_password="testhash",
        role=UserRole.PATIENT,
    )

    doctor_user = User(
        email="doctor@test.com",
        hashed_password="testhash",
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
    start = datetime.now(UTC)

    appointment = Appointment(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        clinic_id=default_clinic.id,
        scheduled_at=start,
        status="CONFIRMED",
        time_range=Range(
            start,
            start + timedelta(minutes=APPOINTMENT_DURATION_MINUTES),
        )
    )

    db.add(appointment)
    await db.flush()

    # -----------------------------
    # Create pending payment
    # -----------------------------
    payment = Payment(
        appointment_id=appointment.id,
        patient_id=patient_user.id,
        clinic_id=default_clinic.id,
        amount=500,
        method="bkash",
        status="PENDING",
        gateway_payment_id="test123",
    )

    db.add(payment)
    await db.commit()

    payload = {
        "paymentID": "test123",
    }

    mock_response = {
        "transactionStatus": "Completed",
        "trxID": "trx_001",
        "amount": "500",
    }

    execute_mock = AsyncMock(
        return_value=mock_response
    )

    with patch(
        "app.services.payment_webhook_service.BkashService.execute_payment",
        new=execute_mock,
    ):
        # -----------------------------
        # First webhook
        # -----------------------------
        response1 = await client.post(
            "/payments/webhook/bkash",
            json=payload,
        )

        # -----------------------------
        # Second webhook (replay)
        # -----------------------------
        response2 = await client.post(
            "/payments/webhook/bkash",
            json=payload,
        )

    # -----------------------------
    # Responses
    # -----------------------------
    assert response1.status_code == 200
    assert response2.status_code == 200

    assert response1.json() == {
        "status": "ok",
    }

    assert response2.json() == {
        "status": "ok",
    }

    # -----------------------------
    # execute_payment called once
    # -----------------------------
    assert execute_mock.await_count == 1

    # -----------------------------
    # Payment still SUCCESS
    # -----------------------------
    result = await db.execute(
        select(Payment)
    )

    updated_payment = result.scalar_one()

    assert updated_payment.status == "SUCCESS"
    assert updated_payment.transaction_id == "trx_001"

    # -----------------------------
    # Only one audit log
    # -----------------------------
    result = await db.execute(
        select(func.count())
        .select_from(PaymentAuditLog)
    )

    audit_count = result.scalar_one()

    assert audit_count == 1



@pytest.mark.asyncio
async def test_bkash_webhook_amount_mismatch(
    client: AsyncClient,
    db,
    default_clinic,
):
    patient_user = User(
        email="patient@test.com",
        hashed_password="testhash",
        role=UserRole.PATIENT,
    )

    doctor_user = User(
        email="doctor@test.com",
        hashed_password="testhash",
        role=UserRole.DOCTOR,
    )

    db.add_all([patient_user, doctor_user])
    await db.flush()

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

    patient = Patient(
        user_id=patient_user.id,
        phone="01700000000",
        address="Rangpur",
        date_of_birth=date(1995, 1, 1),
        gender="MALE",
    )

    db.add(patient)
    await db.flush()

    start = datetime.now(UTC)

    appointment = Appointment(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        clinic_id=default_clinic.id,
        scheduled_at=start,
        status="CONFIRMED",
        time_range=Range(
            start,
            start + timedelta(minutes=APPOINTMENT_DURATION_MINUTES),
        )
    )

    db.add(appointment)
    await db.flush()

    payment = Payment(
        appointment_id=appointment.id,
        patient_id=patient_user.id,
        clinic_id=default_clinic.id,
        amount=500,
        method="bkash",
        status="PENDING",
        gateway_payment_id="test123",
    )

    db.add(payment)
    await db.commit()

    payload = {
        "paymentID": "test123",
    }

    mock_response = {
        "transactionStatus": "Completed",
        "trxID": "trx_001",
        "amount": "1000",  # mismatch
    }

    with patch(
        "app.services.payment_webhook_service.BkashService.execute_payment",
        new=AsyncMock(return_value=mock_response),
    ):
        response = await client.post(
            "/payments/webhook/bkash",
            json=payload,
        )

    assert response.status_code == 200

    assert response.json() == {
        "status": "amount_mismatch",
    }

    result = await db.execute(
        select(Payment)
    )

    updated_payment = result.scalar_one()

    assert updated_payment.status == "PENDING"

    result = await db.execute(
        select(PaymentAuditLog)
    )

    audit_log = result.scalar_one()

    assert (
        audit_log.event_type
        == "webhook_amount_mismatch"
    )



@pytest.mark.asyncio
async def test_bkash_webhook_failed_payment(
    client: AsyncClient,
    db,
    default_clinic,
):
    patient_user = User(
        email="patient@test.com",
        hashed_password="testhash",
        role=UserRole.PATIENT,
    )

    doctor_user = User(
        email="doctor@test.com",
        hashed_password="testhash",
        role=UserRole.DOCTOR,
    )

    db.add_all([patient_user, doctor_user])
    await db.flush()

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

    patient = Patient(
        user_id=patient_user.id,
        phone="01700000000",
        address="Rangpur",
        date_of_birth=date(1995, 1, 1),
        gender="MALE",
    )

    db.add(patient)
    await db.flush()

    start = datetime.now(UTC)

    appointment = Appointment(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        clinic_id=default_clinic.id,
        scheduled_at=start,
        status="CONFIRMED",
        time_range=Range(
            start,
            start + timedelta(minutes=APPOINTMENT_DURATION_MINUTES),
        )
    )

    db.add(appointment)
    await db.flush()

    payment = Payment(
        appointment_id=appointment.id,
        patient_id=patient_user.id,
        clinic_id=default_clinic.id,
        amount=500,
        method="bkash",
        status="PENDING",
        gateway_payment_id="test123",
    )

    db.add(payment)
    await db.commit()

    payload = {
        "paymentID": "test123",
    }

    mock_response = {
        "transactionStatus": "Cancelled",
    }

    with patch(
        "app.services.payment_webhook_service.BkashService.execute_payment",
        new=AsyncMock(return_value=mock_response),
    ):
        response = await client.post(
            "/payments/webhook/bkash",
            json=payload,
        )

    assert response.status_code == 200

    assert response.json() == {
        "status": "failed",
    }

    result = await db.execute(
        select(Payment)
    )

    updated_payment = result.scalar_one()

    assert updated_payment.status == "FAILED"

    result = await db.execute(
        select(PaymentAuditLog)
    )

    audit_log = result.scalar_one()

    assert (
        audit_log.event_type
        == "payment_failed"
    )



@pytest.mark.asyncio
async def test_bkash_webhook_payment_not_found(
    client: AsyncClient,
):
    payload = {
        "paymentID": "missing-payment",
    }

    mock_response = {
        "transactionStatus": "Completed",
        "trxID": "trx_001",
        "amount": "500",
    }

    with patch(
        "app.services.payment_webhook_service.BkashService.execute_payment",
        new=AsyncMock(return_value=mock_response),
    ):
        response = await client.post(
            "/payments/webhook/bkash",
            json=payload,
        )

    assert response.status_code == 404

    assert (
        response.json()["error"]["type"]
        == "NotFoundError"
    )

    assert (
        response.json()["error"]["message"]
        == "Payment not found"
    )
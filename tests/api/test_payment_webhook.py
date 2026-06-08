
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient
from datetime import datetime
from sqlalchemy import select,text

from app.core.time import UTC
from app.models.user import User, UserRole
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.appointment import Appointment
from app.models.payment import Payment
from app.models.payment_audit_log import PaymentAuditLog
from datetime import timedelta
from sqlalchemy.dialects.postgresql import Range



@pytest.mark.asyncio
async def test_bkash_webhook_success(client: AsyncClient, db):




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
        specialization="Cardiology",
        experience_years=5,
        bio="Cardiology specialist",
        is_verified=True,
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
        date_of_birth="1995-01-01",
        gender="male",
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
        scheduled_at=start,
        status="CONFIRMED",
        time_range=Range(start, start + timedelta(minutes=30)),
    )
    db.add(appointment)
    await db.flush()

    # -----------------------------
    # Create pending payment
    # -----------------------------
    payment = Payment(
        appointment_id=appointment.id,
        patient_id=patient_user.id,
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
        "trxID": "trx_001",
        "amount": "500",
    }

    # -----------------------------
    # Mock bKash API
    # -----------------------------
    with patch(
        "app.api.routes.payments.BkashService.execute_payment",
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
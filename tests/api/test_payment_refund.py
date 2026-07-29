from datetime import date
from decimal import Decimal
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.core.time import UTC
from app.models.appointment import Appointment
from app.models.doctor import Doctor
from app.models.enums.payment_status import PaymentStatus
from app.models.patient import Patient
from app.models.payment import Payment
from app.models.user import User, UserRole


async def create_success_payment(
    db,
    default_clinic,
    doctor: Doctor,
):
    patient_user = User(
        email="patient@test.com",
        hashed_password="hash",
        role=UserRole.PATIENT,
    )

    db.add(patient_user)
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
    await db.refresh(payment)

    return payment


def mock_bkash_refund():
    return patch(
        "app.services.payment_refund_service.BkashService.refund_payment",
        new=AsyncMock(
            return_value={
                "transactionStatus": "Completed",
                "refundTransactionId": "bkash-refund-txn-001",
            }
        ),
    )


@pytest.mark.asyncio
async def test_refund_endpoint_success(
    client,
    db,
    default_clinic,
    auth_doctor,
):
    payment = await create_success_payment(
        db=db,
        default_clinic=default_clinic,
        doctor=auth_doctor["doctor"],
    )

    with mock_bkash_refund():
        response = await client.post(
            f"/payments/{payment.id}/refund",
            json={
                "amount": "100",
                "reason": "Patient requested refund",
            },
            headers=auth_doctor["headers"],
        )

    assert response.status_code == 200

    body = response.json()

    assert body["payment_id"] == payment.id
    assert body["status"] == "REFUNDED"
    assert body["refunded_amount"] == "100.00"

    assert body["refund_transaction_id"] is not None
    assert body["refunded_at"] is not None


@pytest.mark.asyncio
async def test_refund_endpoint_payment_not_found(
    client,
    auth_doctor,
):
    response = await client.post(
        "/payments/999999/refund",
        json={
            "amount": "100",
            "reason": "Patient requested refund",
        },
        headers=auth_doctor["headers"],
    )

    assert response.status_code == 404

    body = response.json()

    assert body["error"]["type"] == "NotFoundError"
    assert body["error"]["message"] == "Payment not found"



@pytest.mark.asyncio
async def test_refund_endpoint_forbidden(
    client,
    db,
    default_clinic,
    auth_patient,
    auth_doctor,
):
    payment = await create_success_payment(
        db=db,
        default_clinic=default_clinic,
        doctor=auth_doctor["doctor"],
    )

    response = await client.post(
        f"/payments/{payment.id}/refund",
        json={
            "amount": "100",
            "reason": "Patient requested refund",
        },
        headers=auth_patient["headers"],
    )

    assert response.status_code == 403

    body = response.json()

    assert body["detail"] == "Permission denied"



@pytest.mark.asyncio
async def test_refund_endpoint_invalid_amount(
    client,
    db,
    default_clinic,
    auth_doctor,
):
    payment = await create_success_payment(
        db=db,
        default_clinic=default_clinic,
        doctor=auth_doctor["doctor"],
    )

    response = await client.post(
        f"/payments/{payment.id}/refund",
        json={
            "amount": 0,
            "reason": "Patient requested refund",
        },
        headers=auth_doctor["headers"],
    )

    assert response.status_code == 422

    body = response.json()

    errors = body["detail"]

    assert any(
        error["loc"] == ["body", "amount"]
        and error["type"] == "greater_than"
        for error in errors
    )



@pytest.mark.asyncio
async def test_refund_endpoint_already_refunded(
    client,
    db,
    default_clinic,
    auth_doctor,
):
    payment = await create_success_payment(
        db=db,
        default_clinic=default_clinic,
        doctor=auth_doctor["doctor"],
    )

    with mock_bkash_refund():
        response = await client.post(
            f"/payments/{payment.id}/refund",
            json={
                "amount": "100",
                "reason": "Patient requested refund",
            },
            headers=auth_doctor["headers"],
        )

        assert response.status_code == 200

        response = await client.post(
            f"/payments/{payment.id}/refund",
            json={
                "amount": "100",
                "reason": "Patient requested refund",
            },
            headers=auth_doctor["headers"],
        )

    assert response.status_code == 400

    body = response.json()

    assert body["error"]["type"] == "BadRequestError"
    assert body["error"]["message"] == (
        "Payment has already been refunded"
    )
import re
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.core.time import UTC
from app.models.appointment import Appointment, AppointmentStatus
from app.models.payment import Payment
from app.models.enums.payment_status import PaymentStatus
from app.integrations.fake_gateway import FakePaymentGateway


async def _pending_appointment(db, patient_id, doctor, clinic_id):
    appt = Appointment(
        patient_id=patient_id,
        doctor_id=doctor.id,
        clinic_id=clinic_id,
        consultation_fee=Decimal("500"),
        scheduled_at=datetime.now(UTC),
        status=AppointmentStatus.PENDING,
    )
    db.add(appt)
    await db.flush()
    return appt


@pytest.mark.asyncio
async def test_fake_payment_initiate_and_webhook_confirms_appointment(
    client, db, default_clinic, doctor, auth_patient
):
    appt = await _pending_appointment(
        db, auth_patient["user"].id, doctor, default_clinic.id
    )

    # Initiate — fake gateway returns a simulate-page URL.
    with patch(
        "app.api.routes.payments.get_payment_gateway",
        return_value=FakePaymentGateway(),
    ):
        res = await client.post(
            f"/payments/bkash/initiate?appointment_id={appt.id}",
            headers=auth_patient["headers"],
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "/pay/simulate" in body["bkash_url"]
    payment_id = re.search(r"paymentID=([^&]+)", body["bkash_url"]).group(1)

    # The simulate page fires the real webhook → fake execute → Completed.
    with patch(
        "app.services.payment_webhook_service.get_payment_gateway",
        return_value=FakePaymentGateway(),
    ):
        wh = await client.post("/payments/webhook/bkash", json={"paymentID": payment_id})
    assert wh.status_code == 200, wh.text

    # Payment succeeded AND the appointment auto-confirmed.
    await db.refresh(appt)
    assert appt.status == AppointmentStatus.CONFIRMED
    payment = await db.scalar(
        select(Payment).where(Payment.appointment_id == appt.id)
    )
    assert payment.status == PaymentStatus.SUCCESS


@pytest.mark.asyncio
async def test_fake_payment_failure_leaves_appointment_pending(
    client, db, default_clinic, doctor, auth_patient
):
    appt = await _pending_appointment(
        db, auth_patient["user"].id, doctor, default_clinic.id
    )

    with patch(
        "app.api.routes.payments.get_payment_gateway",
        return_value=FakePaymentGateway(),
    ):
        res = await client.post(
            f"/payments/bkash/initiate?appointment_id={appt.id}",
            headers=auth_patient["headers"],
        )
    payment_id = re.search(r"paymentID=([^&]+)", res.json()["bkash_url"]).group(1)

    # Flip the outcome to failure (as the "simulate failure" button would).
    from app.integrations.fake_gateway import set_outcome

    assert set_outcome(payment_id, "failure")

    with patch(
        "app.services.payment_webhook_service.get_payment_gateway",
        return_value=FakePaymentGateway(),
    ):
        await client.post("/payments/webhook/bkash", json={"paymentID": payment_id})

    await db.refresh(appt)
    assert appt.status == AppointmentStatus.PENDING
    payment = await db.scalar(
        select(Payment).where(Payment.appointment_id == appt.id)
    )
    assert payment.status != PaymentStatus.SUCCESS

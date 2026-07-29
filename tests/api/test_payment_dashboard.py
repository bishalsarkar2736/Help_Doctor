from decimal import Decimal

import pytest

from app.models.enums.payment_status import PaymentStatus
from tests.helpers.payment import create_success_payment



@pytest.mark.asyncio
async def test_payment_dashboard_doctor_success(
    client,
    db,
    default_clinic,
    auth_doctor,
):
    await create_success_payment(
        db=db,
        default_clinic=default_clinic,
    )

    response = await client.get(
        "/admin/dashboard/payment",
        headers=auth_doctor["headers"],
    )

    assert response.status_code == 200

    body = response.json()

    assert "total_payments" in body
    assert "successful_payments" in body
    assert "refund_count" in body



@pytest.mark.asyncio
async def test_payment_dashboard_admin_success(
    client,
    db,
    default_clinic,
    auth_admin,
):
    await create_success_payment(
        db=db,
        default_clinic=default_clinic,
    )

    response = await client.get(
        f"/admin/dashboard/payment?clinic_id={default_clinic.id}",
        headers=auth_admin["headers"],
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_payment_dashboard_admin_requires_clinic_id(
    client,
    auth_admin,
):
    response = await client.get(
        "/admin/dashboard/payment",
        headers=auth_admin["headers"],
    )

    assert response.status_code == 403

    body = response.json()

    assert body["error"]["type"] == "ForbiddenError"

    assert (
        body["error"]["message"]
        == "clinic_id required for admin"
    )


@pytest.mark.asyncio
async def test_payment_dashboard_forbidden(
    client,
    auth_patient,
):
    response = await client.get(
        "/admin/dashboard/payment",
        headers=auth_patient["headers"],
    )

    assert response.status_code == 403

    body = response.json()

    assert body["detail"] == "Permission denied"



@pytest.mark.asyncio
async def test_payment_dashboard_returns_metrics(
    client,
    db,
    default_clinic,
    auth_doctor,
):
    payment1 = await create_success_payment(
        db=db,
        default_clinic=default_clinic,
    )

    await create_success_payment(
        db=db,
        default_clinic=default_clinic,
    )

    await create_success_payment(
        db=db,
        default_clinic=default_clinic,
    )

    payment1.status = PaymentStatus.REFUNDED
    payment1.refunded_amount = Decimal("500")

    await db.commit()

    response = await client.get(
        "/admin/dashboard/payment",
        headers=auth_doctor["headers"],
    )

    assert response.status_code == 200

    body = response.json()

    assert body["total_payments"] == 3
    assert body["successful_payments"] == 2
    assert body["refund_count"] == 1

    assert (
        body["total_payment_amount"]
        == "1000.00"
    )

    assert (
        body["total_refunded_amount"]
        == "500.00"
    )

    assert body["refund_rate"] == 50.0
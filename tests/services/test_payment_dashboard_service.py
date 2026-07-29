from decimal import Decimal

import pytest

from app.models.enums.payment_status import PaymentStatus
from app.services.payment_dashboard_service import (
    get_payment_dashboard_metrics,
)
from tests.helpers.payment import (
    create_success_payment,
)


@pytest.mark.asyncio
async def test_dashboard_total_payments(
    db,
    default_clinic,
):
    await create_success_payment(
        db=db,
        default_clinic=default_clinic,
    )

    await create_success_payment(
        db=db,
        default_clinic=default_clinic,
    )

    metrics = await get_payment_dashboard_metrics(
        db=db,
        clinic_id=default_clinic.id,
    )

    assert metrics["total_payments"] == 2


@pytest.mark.asyncio
async def test_dashboard_successful_payments(
    db,
    default_clinic,
):
    await create_success_payment(
        db=db,
        default_clinic=default_clinic,
    )

    await create_success_payment(
        db=db,
        default_clinic=default_clinic,
    )

    metrics = await get_payment_dashboard_metrics(
        db=db,
        clinic_id=default_clinic.id,
    )

    assert metrics["successful_payments"] == 2


@pytest.mark.asyncio
async def test_dashboard_total_payment_amount(
    db,
    default_clinic,
):
    await create_success_payment(
        db=db,
        default_clinic=default_clinic,
    )

    await create_success_payment(
        db=db,
        default_clinic=default_clinic,
    )

    metrics = await get_payment_dashboard_metrics(
        db=db,
        clinic_id=default_clinic.id,
    )

    assert (
        metrics["total_payment_amount"]
        == Decimal("1000")
    )



@pytest.mark.asyncio
async def test_dashboard_refund_count(
    db,
    default_clinic,
    auth_doctor,
):
    payment = await create_success_payment(
        db=db,
        default_clinic=default_clinic,
    )

    payment.status = PaymentStatus.REFUNDED
    payment.refunded_amount = Decimal("500")

    await db.commit()

    metrics = await get_payment_dashboard_metrics(
        db=db,
        clinic_id=default_clinic.id,
    )

    assert metrics["refund_count"] == 1


@pytest.mark.asyncio
async def test_dashboard_total_refunded_amount(
    db,
    default_clinic,
):
    payment = await create_success_payment(
        db=db,
        default_clinic=default_clinic,
    )

    payment.status = PaymentStatus.REFUNDED
    payment.refunded_amount = Decimal("500")

    await db.commit()

    metrics = await get_payment_dashboard_metrics(
        db=db,
        clinic_id=default_clinic.id,
    )

    assert (
        metrics["total_refunded_amount"]
        == Decimal("500")
    )


@pytest.mark.asyncio
async def test_dashboard_refund_rate(
    db,
    default_clinic,
):
    payment1 = await create_success_payment(
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

    metrics = await get_payment_dashboard_metrics(
        db=db,
        clinic_id=default_clinic.id,
    )

    assert metrics["successful_payments"] == 1
    assert metrics["refund_count"] == 1
    assert metrics["refund_rate"] == 100.0
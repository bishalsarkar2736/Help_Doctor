from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums.payment_status import PaymentStatus
from app.models.payment import Payment


async def get_payment_dashboard_metrics(
    *,
    db: AsyncSession,
    clinic_id: int,
) -> dict:
    """
    Return payment dashboard metrics for a clinic.
    """

    # ---------------------------------
    # Total payments
    # ---------------------------------
    total_payments = await db.scalar(
        select(func.count(Payment.id)).where(
            Payment.clinic_id == clinic_id
        )
    )

    total_payments = total_payments or 0

    # ---------------------------------
    # Successful payments
    # ---------------------------------
    successful_payments = await db.scalar(
        select(func.count(Payment.id)).where(
            Payment.clinic_id == clinic_id,
            Payment.status == PaymentStatus.SUCCESS,
        )
    )

    successful_payments = successful_payments or 0

    # ---------------------------------
    # Total payment amount
    # ---------------------------------
    total_payment_amount = await db.scalar(
        select(func.sum(Payment.amount)).where(
            Payment.clinic_id == clinic_id,
            Payment.status == PaymentStatus.SUCCESS,
        )
    )

    total_payment_amount = (
        total_payment_amount
        or Decimal("0")
    )

    # ---------------------------------
    # Refund count
    # ---------------------------------
    refund_count = await db.scalar(
        select(func.count(Payment.id)).where(
            Payment.clinic_id == clinic_id,
            Payment.status == PaymentStatus.REFUNDED,
        )
    )

    refund_count = refund_count or 0

    # ---------------------------------
    # Total refunded amount
    # ---------------------------------
    total_refunded_amount = await db.scalar(
        select(func.sum(Payment.refunded_amount)).where(
            Payment.clinic_id == clinic_id,
            Payment.status == PaymentStatus.REFUNDED,
        )
    )

    total_refunded_amount = (
        total_refunded_amount
        or Decimal("0")
    )

    # ---------------------------------
    # Refund rate
    # ---------------------------------
    refund_rate = (
        (refund_count / successful_payments) * 100
        if successful_payments
        else 0.0
    )

    return {
        "total_payments": total_payments,
        "successful_payments": successful_payments,
        "total_payment_amount": total_payment_amount,
        "refund_count": refund_count,
        "total_refunded_amount": total_refunded_amount,
        "refund_rate": refund_rate,
    }
from decimal import Decimal
from datetime import datetime, timedelta

from app.core.time import UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.payment_audit_service import (
    create_payment_audit_log,
)
from app.models.payment import Payment
from app.models.enums.payment_status import PaymentStatus
from app.integrations.bkash.bkash_service import BkashService
from app.services.payment_service import (
    mark_payment_success,
    mark_payment_failed,
)
import logging

logger = logging.getLogger(__name__)


async def reconcile_pending_payments(
    *,
    db: AsyncSession,
):
    bkash = BkashService()

    cutoff = datetime.now(UTC) - timedelta(days=7)

    result = await db.execute(
        select(Payment).where(
            Payment.status == PaymentStatus.PENDING,
            Payment.created_at >= cutoff,
            Payment.gateway_payment_id.isnot(None),
        )
    )

    payments = result.scalars().all()

    for payment in payments:

        try:

            response = await bkash.query_payment(
                gateway_payment_id=payment.gateway_payment_id,
            )

            transaction_status = (
                response.get("transactionStatus") or ""
            ).strip().lower()

            if transaction_status == "completed":

                paid_amount = Decimal(response["amount"])

                if paid_amount != payment.amount:
                    logger.error(
                        "payment_amount_mismatch",
                        extra={
                            "payment_id": payment.id,
                            "expected": str(payment.amount),
                            "received": str(paid_amount),
                        },
                    )

                    await create_payment_audit_log(
                        db=db,
                        payment_id=payment.id,
                        gateway="bkash",
                        event_type="reconciliation_amount_mismatch",
                        payload=response,
                    )
                    
                    continue

                updated_payment = await mark_payment_success(
                    db=db,
                    transaction_id=response["trxID"],
                    gateway_payment_id=payment.gateway_payment_id,
                    paid_amount=paid_amount,
                    correlation_id="reconciliation-job",
                )

                await create_payment_audit_log(
                    db=db,
                    payment_id=updated_payment.id,
                    gateway="bkash",
                    event_type="reconciliation_success",
                    payload=response,
                )

            elif transaction_status in {
                "failed",
                "cancelled",
                "expired",
            }:

                updated_payment = await mark_payment_failed(
                    db=db,
                    gateway_payment_id=payment.gateway_payment_id,
                    reason=transaction_status,
                )

                await create_payment_audit_log(
                    db=db,
                    payment_id=updated_payment.id,
                    gateway="bkash",
                    event_type="reconciliation_failed",
                    payload=response,
                )

            else:
                logger.warning(
                    "unknown_gateway_payment_status",
                    extra={
                        "payment_id": payment.id,
                        "gateway_payment_id": (
                            payment.gateway_payment_id
                        ),
                        "transaction_status": transaction_status,
                    },
                )

                continue


        except Exception:
            logger.exception(
                "payment_reconciliation_failed",
                extra={
                    "payment_id": payment.id,
                },
            )
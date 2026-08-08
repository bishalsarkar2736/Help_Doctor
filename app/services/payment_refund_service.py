from decimal import Decimal
from datetime import datetime
import logging

from app.core.time import UTC
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.payment_gateway_factory import get_payment_gateway
# Kept importable so tests can patch BkashService.refund_payment; the live
# gateway is resolved via get_payment_gateway() (real BkashService unless fake).
from app.integrations.bkash.bkash_service import BkashService  # noqa: F401
from app.models.doctor import Doctor
from app.models.enums.payment_status import PaymentStatus
from app.models.payment import Payment
from app.models.user import User, UserRole
from app.try_except.exceptions import (
    BadRequestError,
    ExternalServiceError,
    ForbiddenError,
    NotFoundError,
)

logger = logging.getLogger(__name__)
from app.services.payment_audit_service import (
    create_payment_audit_log,
)
from app.schemas.event import PaymentRefundedEvent
from app.services.domain_event_service import (
    publish_domain_event,
)
from app.schemas.event_metadata import EventActor


async def get_locked_payment(
    *,
    db: AsyncSession,
    payment_id: int,
) -> Payment:
    result = await db.execute(
        select(Payment)
        .where(Payment.id == payment_id)
        .with_for_update()
    )

    payment = result.scalar_one_or_none()

    if payment is None:
        raise NotFoundError(
            "Payment not found"
        )

    return payment



async def get_refunding_doctor(
    *,
    db: AsyncSession,
    user: User,
) -> Doctor | None:
    
    return await db.scalar(
        select(Doctor).where(
            Doctor.user_id == user.id
        )
    )


async def execute_gateway_refund(
    *,
    payment: Payment,
    amount: Decimal,
    reason: str,
) -> str:
    """
    Call the payment gateway to actually move the money back,
    and return the gateway's refund transaction id.
    Raises ExternalServiceError if the gateway doesn't confirm
    the refund - callers must not mark the payment REFUNDED
    unless this succeeds.
    """
    if payment.method != "bkash":
        raise BadRequestError(
            f"Refunds are not supported for payment method '{payment.method}'"
        )

    if not payment.transaction_id or not payment.gateway_payment_id:
        raise BadRequestError(
            "Payment is missing gateway transaction details"
        )

    try:
        result = await get_payment_gateway().refund_payment(
            gateway_payment_id=payment.gateway_payment_id,
            transaction_id=payment.transaction_id,
            amount=amount,
            reason=reason,
        )
    except Exception as exc:
        logger.exception(
            "gateway_refund_failed",
            extra={"payment_id": payment.id, "gateway": payment.method},
        )
        raise ExternalServiceError(
            "Payment gateway refund failed"
        ) from exc

    if result.get("transactionStatus") != "Completed":
        logger.error(
            "gateway_refund_not_completed",
            extra={
                "payment_id": payment.id,
                "gateway": payment.method,
                "result": result,
            },
        )
        raise ExternalServiceError(
            "Payment gateway did not confirm the refund"
        )

    return (
        result.get("refundTransactionId")
        or result.get("trxID")
        or f"bkash-refund-{payment.gateway_payment_id}"
    )


async def refund_payment(
    *,
    db: AsyncSession,
    payment_id: int,
    refunded_by: User,
    amount: Decimal,
    reason: str,
):
    payment = await get_locked_payment(
        db=db,
        payment_id=payment_id,
    )

    validate_refund_request(
        payment=payment,
        amount=amount,
        reason=reason,
    )

    await validate_refund_access(
        db=db,
        refunded_by=refunded_by,
        payment=payment,
    )

    # -------------------------------------------------
    # Call the payment gateway first - only mark the
    # payment as refunded once the gateway confirms the
    # money actually moved.
    # -------------------------------------------------

    refund_transaction_id = await execute_gateway_refund(
        payment=payment,
        amount=amount,
        reason=reason,
    )

    payment.status = PaymentStatus.REFUNDED

    payment.refunded_amount = amount

    payment.refunded_at = datetime.now(UTC)

    payment.refund_transaction_id = (
        refund_transaction_id
    )

    metadata = payment.payment_metadata or {}

    metadata["refund_reason"] = reason

    metadata["refunded_by"] = refunded_by.id

    payment.payment_metadata = metadata

    await db.flush()

    await create_payment_audit_log(
        db=db,
        payment_id=payment.id,
        gateway=payment.method,
        event_type="payment_refunded",
        payload={
            "refund_transaction_id": payment.refund_transaction_id,
            "refunded_amount": str(payment.refunded_amount),
            "reason": reason,
            "refunded_by": refunded_by.id,
        },
    )

    
    await publish_domain_event(
        db=db,
        event=PaymentRefundedEvent(
            event_type="PAYMENT_REFUNDED",

            occurred_at=datetime.now(UTC).isoformat(),
            aggregate_type="payment",
            aggregate_id=payment.id,

            actor=EventActor(
                id=refunded_by.id,
                role=refunded_by.role.value,
            ),

            # The patient, not the admin who processed it. Every other event
            # here uses user_id for the RECIPIENT -- PAYMENT_SUCCESS uses
            # payment.patient_id, appointment events use patient_id or
            # doctor.user_id -- and `actor` above already records who acted.
            #
            # This said refunded_by.id, so wiring up the handler alone would
            # have sent "Your payment of X has been refunded" to the
            # administrator who issued it, leaving the patient uninformed.
            user_id=payment.patient_id,
            appointment_id=payment.appointment_id,
            payment_id=payment.id,
            refund_transaction_id=payment.refund_transaction_id,
            refunded_amount=str(payment.refunded_amount),
        ),
    )

    return payment


def validate_refund_request(
    *,
    payment: Payment,
    amount: Decimal,
    reason: str,
) -> None:
    """
    Validate business rules for refund requests.
    """

    # ---------------------------------
    # Already refunded
    # ---------------------------------
    if payment.status == PaymentStatus.REFUNDED:
        raise BadRequestError(
            "Payment has already been refunded"
        )

    # ---------------------------------
    # Payment must be SUCCESS
    # ---------------------------------
    if payment.status != PaymentStatus.SUCCESS:
        raise BadRequestError(
            "Only successful payments can be refunded"
        )

    # ---------------------------------
    # Refund reason
    # ---------------------------------
    if not reason.strip():
        raise BadRequestError(
            "Refund reason is required"
        )

    # ---------------------------------
    # Positive amount
    # ---------------------------------
    if amount <= 0:
        raise BadRequestError(
            "Refund amount must be greater than zero"
        )

    # ---------------------------------
    # Cannot exceed payment amount
    # ---------------------------------
    if amount > payment.amount:
        raise BadRequestError(
            "Refund amount exceeds payment amount"
        )


async def validate_refund_access(
    *,
    db: AsyncSession,
    refunded_by: User,
    payment: Payment,
) -> None:
    """
    Validate that the user is authorized
    to refund this payment.
    """

    # ---------------------------------
    # Admin can refund any payment
    # ---------------------------------
    if refunded_by.role == UserRole.ADMIN:
        return

    # ---------------------------------
    # Reject everyone except doctors
    # ---------------------------------
    if refunded_by.role != UserRole.DOCTOR:
        raise ForbiddenError(
            "You do not have permission to refund payments"
        )

    # ---------------------------------
    # Doctor profile must exist
    # ---------------------------------
    doctor = await get_refunding_doctor(
        db=db,
        user=refunded_by,
    )

    if doctor is None:
        raise ForbiddenError(
            "Doctor profile not found"
        )

    # ---------------------------------
    # Doctor must belong to same clinic
    # ---------------------------------
    if doctor.clinic_id != payment.clinic_id:
        raise ForbiddenError(
            "Payment does not belong to your clinic"
        )
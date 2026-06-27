from decimal import Decimal
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.bkash.bkash_service import BkashService
from app.models.idempotency_key import IdempotencyKey
from app.models.payment import Payment
from app.schemas.payment_webhook import BkashWebhookSchema
from app.services.idempotency_service import (
    create_request_hash,
    get_existing_key,
    save_response,
    store_key,
)
from app.services.payment_audit_service import (
    create_payment_audit_log,
)
from app.services.payment_service import (
    mark_payment_failed,
    mark_payment_success,
)
from app.try_except.exceptions import (
    BadRequestError,
    NotFoundError,
)

logger = logging.getLogger(__name__)

BKASH_WEBHOOK_USER_ID = 0


async def process_bkash_webhook(
    *,
    db: AsyncSession,
    payload: BkashWebhookSchema,
) -> dict:
    gateway_payment_id = payload.paymentID

    idempotency_record, stored_response = (
        await _get_or_create_webhook_idempotency(
            db=db,
            gateway_payment_id=gateway_payment_id,
            payload=payload,
        )
    )

    if stored_response is not None:
        return stored_response

    try:
        bkash = BkashService()

        result = await bkash.execute_payment(
            gateway_payment_id=gateway_payment_id,
        )

        logger.info(
            "bkash_execute_response",
            extra={
                "gateway_payment_id": gateway_payment_id,
                "result": result,
            },
        )

        transaction_status = result.get(
            "transactionStatus"
        )

        if transaction_status != "Completed":
            return await _handle_failed_bkash_payment(
                db=db,
                idempotency_record=idempotency_record,
                gateway_payment_id=gateway_payment_id,
                result=result,
                transaction_status=transaction_status,
            )

        payment = await _get_payment_by_gateway_payment_id(
            db=db,
            gateway_payment_id=gateway_payment_id,
        )

        received_amount = Decimal(result["amount"])

        if received_amount != payment.amount:
            return await _handle_amount_mismatch(
                db=db,
                idempotency_record=idempotency_record,
                payment=payment,
                result=result,
                received_amount=received_amount,
            )

        return await _handle_successful_bkash_payment(
            db=db,
            idempotency_record=idempotency_record,
            gateway_payment_id=gateway_payment_id,
            result=result,
        )

    except Exception:
        logger.exception(
            "bkash_webhook_processing_failed",
            extra={
                "gateway_payment_id": gateway_payment_id,
            },
        )
        raise


async def _get_or_create_webhook_idempotency(
    *,
    db: AsyncSession,
    gateway_payment_id: str,
    payload: BkashWebhookSchema,
) -> tuple[IdempotencyKey, dict | None]:
    request_hash = create_request_hash(
        payload.model_dump()
    )

    idempotency_record = await get_existing_key(
        db=db,
        key=gateway_payment_id,
        user_id=BKASH_WEBHOOK_USER_ID,
    )

    if idempotency_record:
        if idempotency_record.request_hash != request_hash:
            logger.error(
                "idempotency_key_payload_conflict",
                extra={
                    "gateway_payment_id": gateway_payment_id,
                },
            )
            raise BadRequestError(
                "Idempotency key conflict"
            )

        if idempotency_record.response_body:
            return (
                idempotency_record,
                idempotency_record.response_body,
            )

        return idempotency_record, None

    idempotency_record = await store_key(
        db=db,
        key=gateway_payment_id,
        user_id=BKASH_WEBHOOK_USER_ID,
        request_hash=request_hash,
    )

    return idempotency_record, None


async def _get_payment_by_gateway_payment_id(
    *,
    db: AsyncSession,
    gateway_payment_id: str,
) -> Payment:
    result = await db.execute(
        select(Payment).where(
            Payment.gateway_payment_id
            == gateway_payment_id
        )
        .with_for_update()
    )

    payment = result.scalar_one_or_none()

    if not payment:
        raise NotFoundError(
            "Payment not found"
        )

    return payment


async def _handle_failed_bkash_payment(
    *,
    db: AsyncSession,
    idempotency_record: IdempotencyKey,
    gateway_payment_id: str,
    result: dict,
    transaction_status: str | None,
) -> dict:
    payment = await mark_payment_failed(
        db=db,
        gateway_payment_id=gateway_payment_id,
        reason=transaction_status or "unknown",
    )

    await create_payment_audit_log(
        db=db,
        payment_id=payment.id,
        gateway="bkash",
        event_type="payment_failed",
        payload=result,
    )

    response = {
        "status": "failed",
    }

    await save_response(
        db=db,
        record=idempotency_record,
        response_body=response,
        status_code=200,
    )

    return response


async def _handle_amount_mismatch(
    *,
    db: AsyncSession,
    idempotency_record: IdempotencyKey,
    payment: Payment,
    result: dict,
    received_amount: Decimal,
) -> dict:
    logger.error(
        "bkash_webhook_amount_mismatch",
        extra={
            "payment_id": payment.id,
            "gateway_payment_id": payment.gateway_payment_id,
            "expected": str(payment.amount),
            "received": str(received_amount),
        },
    )

    await create_payment_audit_log(
        db=db,
        payment_id=payment.id,
        gateway="bkash",
        event_type="webhook_amount_mismatch",
        payload=result,
    )

    response = {
        "status": "amount_mismatch",
    }

    await save_response(
        db=db,
        record=idempotency_record,
        response_body=response,
        status_code=200,
    )

    return response


async def _handle_successful_bkash_payment(
    *,
    db: AsyncSession,
    idempotency_record: IdempotencyKey,
    gateway_payment_id: str,
    result: dict,
) -> dict:
    trx_id = result["trxID"]
    amount = Decimal(result["amount"])

    logger.info(
        "payment_success",
        extra={
            "gateway_payment_id": gateway_payment_id,
            "transaction_id": trx_id,
            "amount": str(amount),
        },
    )

    payment = await mark_payment_success(
        db=db,
        transaction_id=trx_id,
        gateway_payment_id=gateway_payment_id,
        paid_amount=amount,
    )

    await create_payment_audit_log(
        db=db,
        payment_id=payment.id,
        gateway="bkash",
        event_type="execute_payment",
        payload=result,
    )

    response = {
        "status": "ok",
    }

    await save_response(
        db=db,
        record=idempotency_record,
        response_body=response,
        status_code=200,
    )

    return response
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import logging
from app.db.postgres import get_db
from app.services.payment_service import (
    mark_payment_success,
    create_payment,
)
from app.services.payment_audit_service import create_payment_audit_log
from app.integrations.bkash.bkash_service import BkashService
from app.security.rbac import require_roles
from app.schemas.payment_webhook import (
    BkashWebhookSchema,
)
from app.models.user import User,UserRole

# ✅ Idempotency
from app.services.idempotency_service import (
    get_existing_key,
    store_key,
    save_response,
    create_request_hash,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/payments",
    tags=["payments"],
)


@router.post("/webhook/bkash")
async def bkash_webhook(
    payload: BkashWebhookSchema,
    db: AsyncSession = Depends(get_db),
):

    payment_id = payload.paymentID

    # 🔥 Idempotency key
    idempotency_key = payment_id
    user_id = 0  # system webhook

    request_hash = create_request_hash(
        payload.model_dump()
    )

    # =============================
    # 1️⃣ CHECK EXISTING (NO LOCK)
    # =============================
    existing = await get_existing_key(
        db,
        idempotency_key,
        user_id,
    )

    if existing:

        # 🔴 Payload mismatch protection
        if existing.request_hash != request_hash:

            logger.error(
                "Idempotency key reuse with different payload",
                extra={
                    "payment_id": payment_id,
                },
            )

            raise Exception(
                "Idempotency key conflict"
            )

        # ✅ Return stored response
        if existing.response_body:
            return existing.response_body

    else:

        # =============================
        # 2️⃣ CREATE KEY (RACE SAFE)
        # =============================
        existing = await store_key(
            db,
            idempotency_key,
            user_id,
            request_hash,
        )

    # =============================
    # 3️⃣ REAL PROCESSING (SAFE)
    # =============================
    try:

        bkash = BkashService()

        result = await bkash.execute_payment(
            payment_id
        )

        logger.info(
            "bkash_execute_response",
            extra=result,
        )

        trx_id = result["trxID"]
        amount = float(result["amount"])

        logger.info(
            "payment_success",
            extra={
                "transaction_id": trx_id,
                "amount": amount,
            }
        )

        payment = await mark_payment_success(
            db=db,
            transaction_id=trx_id,
            gateway_payment_id=payment_id,
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
            "status": "ok"
        }

        # =============================
        # 4️⃣ SAVE RESPONSE
        # =============================
        await save_response(
            db=db,
            record=existing,
            response_body=response,
            status_code=200,
        )

        return response

    except Exception:

        logger.exception(
            "Bkash webhook processing failed"
        )

        # ❗ no response saved
        # ❗ retry remains safe

        raise



@router.post("/bkash/initiate")
async def initiate_bkash_payment(
    appointment_id: int,
    amount: float,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.PATIENT
        )
    ),
):

    payment = await create_payment(
        db=db,
        appointment_id=appointment_id,
        patient_id=current_user.id,
        amount=amount,
        method="bkash",
    )

    bkash = BkashService()

    response = await bkash.create_payment(
        amount=payment.amount,
        invoice_id=str(payment.id),
    )

    payment.gateway_payment_id = (
        response["paymentID"]
    )

    await db.flush()

    return {
        "payment_id": payment.id,
        "bkash_url": response[
            "bkashURL"
        ],
    }
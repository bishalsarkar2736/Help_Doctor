from fastapi import (
    APIRouter, 
    Depends,
    Request
)
from app.core.limiter import limiter
from sqlalchemy.ext.asyncio import AsyncSession
import logging
from app.db.postgres import get_db
from app.services.payment_service import (
    create_payment,
)
from app.services.payment_webhook_service import process_bkash_webhook
from app.integrations.bkash.bkash_service import BkashService
from app.security.rbac import require_roles
from app.schemas.payment_webhook import (
    BkashWebhookSchema,
)
from app.models.user import User,UserRole




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
    return await process_bkash_webhook(
        db=db,
        payload=payload,
    )



@router.post("/bkash/initiate")
@limiter.limit("10/minute")
async def initiate_bkash_payment(
    request: Request,
    appointment_id: int,
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
        method="bkash",
    )

    bkash = BkashService()

    response = await bkash.create_payment(
        amount=payment.amount,
        invoice_id=payment.public_invoice_id,
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



from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment_audit_log import PaymentAuditLog


async def create_payment_audit_log(
    *,
    db: AsyncSession,
    payment_id: int,
    gateway: str,
    event_type: str,
    payload: dict,
):

    log = PaymentAuditLog(
        payment_id=payment_id,
        gateway=gateway,
        event_type=event_type,
        payload=payload,
    )

    db.add(log)

    await db.flush()

    return log
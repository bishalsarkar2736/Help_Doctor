
from app.db.postgres import AsyncSessionLocal
from app.services.payment_reconciliation_service import (
    reconcile_pending_payments,
)



async def payment_reconciliation_job():

    async with AsyncSessionLocal() as db:

        try:
            await reconcile_pending_payments(
                db=db,
            )

            await db.commit()

        except Exception:
            await db.rollback()
            raise
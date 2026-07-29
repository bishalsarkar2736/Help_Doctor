from decimal import Decimal

from app.config import get_settings
from .bkash_client import BkashClient

settings = get_settings()


class BkashService:

    def __init__(self):
        self.client = BkashClient()

    async def create_payment(
        self,
        *,
        amount: Decimal,
        invoice_id: str,
    ):
        return await self.client.create_payment(
            amount=str(amount),
            invoice_id=invoice_id,
            payer_reference="patient",
            callback_url=settings.BKASH_CALLBACK_URL,
        )

    async def execute_payment(
        self,
        *,
        gateway_payment_id: str,
    ):
        return await self.client.execute_payment(
            gateway_payment_id=gateway_payment_id,
        )

    async def query_payment(
        self,
        *,
        gateway_payment_id: str,
    ):
        return await self.client.query_payment(
            gateway_payment_id=gateway_payment_id,
        )
    

    async def refund_payment(
        self,
        *,
        gateway_payment_id: str,
        transaction_id: str,
        amount: Decimal,
        reason: str,
    ) -> dict:
        return await self.client.refund_payment(
            gateway_payment_id=gateway_payment_id,
            transaction_id=transaction_id,
            amount=str(amount),
            reason=reason,
        )
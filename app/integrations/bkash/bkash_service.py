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
        transaction_id: str,
        amount: Decimal,
    ) -> dict:
        raise NotImplementedError(
            "Bkash refund API not integrated yet"
        )
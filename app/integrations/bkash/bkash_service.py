import httpx
from app.config import Settings
from .bkash_client import BkashClient


class BkashService:

    async def create_payment(
        self,
        amount: float,
        invoice_id: str,
    ):

        token = await BkashClient().get_token()

        url = f"{Settings.BKASH_BASE_URL}/tokenized/checkout/create"

        payload = {
            "mode": "0011",
            "payerReference": "patient",
            "callbackURL": "http://localhost:8000/api/payments/bkash/callback",
            "amount": str(amount),
            "currency": "BDT",
            "intent": "sale",
            "merchantInvoiceNumber": invoice_id,
        }

        headers = {
            "Authorization": token,
            "X-APP-Key": Settings.BKASH_APP_KEY,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                headers=headers,
            )

        response.raise_for_status()

        return response.json()

    async def execute_payment(self, payment_id: str):

        token = await BkashClient().get_token()

        url = f"{Settings.BKASH_BASE_URL}/tokenized/checkout/execute"

        payload = {
            "paymentID": payment_id
        }

        headers = {
            "Authorization": token,
            "X-APP-Key": Settings.BKASH_APP_KEY,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                headers=headers,
            )

        response.raise_for_status()

        return response.json()
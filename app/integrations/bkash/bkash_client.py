
from datetime import UTC, datetime, timedelta

import httpx
from app.utils.http_retry import retry_http_call
from app.config import get_settings

settings = get_settings()


class BkashClient:

    _token: str | None = None
    _token_expiry: datetime | None = None

    async def _post(
        self,
        *,
        url: str,
        payload: dict,
        headers: dict,
    ) -> dict:

        async def _request():

            async with httpx.AsyncClient(
                timeout=30.0,
            ) as client:

                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                )

            response.raise_for_status()

            return response.json()

        return await retry_http_call(
            _request,
            attempts=3,
            base_delay=1.0,
        )
    

    async def get_token(self) -> str:

        now = datetime.now(UTC)

        if (
            self.__class__._token
            and self.__class__._token_expiry
            and now < self.__class__._token_expiry
        ):
            return self.__class__._token

        url = (
            f"{settings.BKASH_BASE_URL}"
            "/tokenized/checkout/token/grant"
        )

        payload = {
            "app_key": settings.BKASH_APP_KEY,
            "app_secret": settings.BKASH_APP_SECRET,
        }

        headers = {
            "username": settings.BKASH_USERNAME,
            "password": settings.BKASH_PASSWORD,
            "Content-Type": "application/json",
        }

        data = await self._post(
            url=url,
            payload=payload,
            headers=headers,
        )

        token = data["id_token"]
        expires_in = int(
            data.get("expires_in", 3600)
        )
        

        self.__class__._token = token

        self.__class__._token_expiry = (
            now
            + timedelta(
                seconds=max(
                    expires_in - 60,
                    60,
                )
            )
        )

        return token
    

    async def create_payment(
        self,
        *,
        amount: str,
        invoice_id: str,
        payer_reference: str,
        callback_url: str,
    ) -> dict:
        token = await self.get_token()

        url = f"{settings.BKASH_BASE_URL}/tokenized/checkout/create"

        payload = {
            "mode": "0011",
            "payerReference": payer_reference,
            "callbackURL": callback_url,
            "amount": amount,
            "currency": "BDT",
            "intent": "sale",
            "merchantInvoiceNumber": invoice_id,
        }

        headers = {
            "Authorization": token,
            "X-APP-Key": settings.BKASH_APP_KEY,
            "Content-Type": "application/json",
        }

        return await self._post(
            url=url,
            payload=payload,
            headers=headers,
        )
    


    async def execute_payment(
        self,
        *,
        gateway_payment_id: str,
    ) -> dict:
        token = await self.get_token()

        url = f"{settings.BKASH_BASE_URL}/tokenized/checkout/execute"

        payload = {"paymentID": gateway_payment_id}

        headers = {
            "Authorization": token,
            "X-APP-Key": settings.BKASH_APP_KEY,
            "Content-Type": "application/json",
        }

        return await self._post(
            url=url,
            payload=payload,
            headers=headers,
        )

    async def query_payment(
        self,
        *,
        gateway_payment_id: str,
    ) -> dict:
        token = await self.get_token()

        url = f"{settings.BKASH_BASE_URL}/tokenized/checkout/payment/status"

        payload = {"paymentID": gateway_payment_id}

        headers = {
            "Authorization": token,
            "X-APP-Key": settings.BKASH_APP_KEY,
            "Content-Type": "application/json",
        }

        return await self._post(
            url=url,
            payload=payload,
            headers=headers,
        )
    

    async def refund_payment(
        self,
        *,
        transaction_id: str,
        amount: str,
    ) -> dict:
        raise NotImplementedError(
            "Bkash refund API not integrated yet"
        )
import httpx
from app.config import Settings


class BkashClient:

    async def get_token(self):

        url = f"{Settings.BKASH_BASE_URL}/tokenized/checkout/token/grant"

        payload = {
            "app_key": Settings.BKASH_APP_KEY,
            "app_secret": Settings.BKASH_APP_SECRET,
        }

        headers = {
            "username": Settings.BKASH_USERNAME,
            "password": Settings.BKASH_PASSWORD,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                headers=headers,
            )

        response.raise_for_status()

        return response.json()["id_token"]
import logging

import httpx

from app.config import get_settings
from app.try_except.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)

settings = get_settings()


class WhatsAppService:

    BASE_URL = "https://graph.facebook.com/v23.0"

    @classmethod
    async def send_document(
        cls,
        *,
        phone: str,
        media_id: str,
        filename: str,
    ):

        url = (
            f"{cls.BASE_URL}/"
            f"{settings.WHATSAPP_PHONE_NUMBER_ID}"
            f"/messages"
        )

        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "document",
            "document": {
                "id": media_id,
                "filename": filename,
            },
        }

        headers = {
            "Authorization": (
                f"Bearer "
                f"{settings.WHATSAPP_ACCESS_TOKEN}"
            ),
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(
            timeout=30
        ) as client:

            response = await client.post(
                url,
                json=payload,
                headers=headers,
            )

        if response.status_code >= 400:

            logger.error(
                "whatsapp_send_document_failed",
                extra={
                    "phone": phone,
                    "status": response.status_code,
                    "response": response.text,
                },
            )

            raise ExternalServiceError(
                "WhatsApp document send failed"
            )

        logger.info(
            "whatsapp_document_sent",
            extra={
                "phone": phone,
            },
        )

        return response.json()

    @classmethod
    async def upload_media(
        cls,
        *,
        pdf_bytes: bytes,
        filename: str,
    ) -> str:

        url = (
            f"{cls.BASE_URL}/"
            f"{settings.WHATSAPP_PHONE_NUMBER_ID}"
            f"/media"
        )

        headers = {
            "Authorization": (
                f"Bearer "
                f"{settings.WHATSAPP_ACCESS_TOKEN}"
            ),
        }

        files = {
            "file": (
                filename,
                pdf_bytes,
                "application/pdf",
            ),
            "messaging_product": (
                None,
                "whatsapp",
            ),
        }

        async with httpx.AsyncClient(
            timeout=60
        ) as client:

            response = await client.post(
                url,
                files=files,
                headers=headers,
            )

        if response.status_code >= 400:

            logger.error(
                "whatsapp_media_upload_failed",
                extra={
                    "status": response.status_code,
                    "response": response.text,
                },
            )

            raise ExternalServiceError(
                "WhatsApp media upload failed"
            )

        media_id = response.json()["id"]

        logger.info(
            "whatsapp_media_uploaded",
            extra={
                "media_id": media_id,
            },
        )

        return media_id
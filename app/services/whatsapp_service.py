import logging
import os

import httpx

from app.config import get_settings
from app.try_except.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)

settings = get_settings()


class WhatsAppService:
    """Meta WhatsApp Cloud API.

    send_document and upload_media were here already and are unchanged.
    send_template is added because a notification cannot use either of them.

    WHY A TEMPLATE AND NOT TEXT
    Meta only accepts free-form messages inside a 24-hour customer-service
    window, which the USER opens by messaging the business. A notification is
    business-initiated, so for any patient who has not just written to the
    clinic — nearly all of them — free-form text is rejected. Business-initiated
    messages must reference a template registered and approved in Meta Business
    Manager.

    That approval is external to this codebase. The template NAMES therefore come
    from configuration rather than being invented here: inventing one would
    compile, pass review, and then fail against Meta with a 400.
    """

    BASE_URL = "https://graph.facebook.com/v23.0"

    @classmethod
    async def send_document(
        cls,
        *,
        phone: str,
        media_id: str,
        filename: str,
    ):

        # Never call Meta during tests. app/services/email.py has had this
        # guard since it was written; this client did not, so wiring it into
        # the live path would have put graph.facebook.com in the test suite.
        if os.getenv("TESTING") == "1":
            return {}

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

        # Never call Meta during tests. app/services/email.py has had this
        # guard since it was written; this client did not, so wiring it into
        # the live path would have put graph.facebook.com in the test suite.
        if os.getenv("TESTING") == "1":
            return {}

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


    @classmethod
    async def send_template(
        cls,
        *,
        phone: str,
        template_name: str,
        language: str = "en",
        body_parameters: list[str] | None = None,
    ):
        """Send a pre-approved template message.

        The only mechanism Meta permits for a business-initiated notification.
        `template_name` must already be approved in Business Manager; an
        unapproved name is a 400 from Meta, which surfaces as
        ExternalServiceError and is retried by the caller like any other
        delivery failure.
        """
        if os.getenv("TESTING") == "1":
            return {}

        url = (
            f"{cls.BASE_URL}/"
            f"{settings.WHATSAPP_PHONE_NUMBER_ID}"
            f"/messages"
        )

        template: dict = {
            "name": template_name,
            "language": {"code": language},
        }

        if body_parameters:
            template["components"] = [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": value}
                        for value in body_parameters
                    ],
                }
            ]

        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "template",
            "template": template,
        }

        headers = {
            "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code >= 400:
            logger.error(
                "whatsapp_send_template_failed",
                extra={
                    "template_name": template_name,
                    "status": response.status_code,
                    "response": response.text,
                },
            )

            raise ExternalServiceError("WhatsApp template send failed")

        logger.info(
            "whatsapp_template_sent",
            extra={"template_name": template_name},
        )

        return response.json()

import logging
import os

import httpx

from app.config import get_settings
from app.try_except.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)

settings = get_settings()


def _error_fingerprint(response: httpx.Response) -> dict:
    """What went wrong, without what it went wrong about.

    These logs used to carry `response.text` verbatim. Meta's 4xx bodies echo
    request context, and the request body is `{"to": <patient phone>, ...}` --
    so the raw text could reproduce the recipient's number even in a log
    statement whose own fields were chosen carefully. JsonFormatter copies every
    `extra` value into the output with no redaction, so whatever lands here is
    what ships.

    Only identifiers are kept. `code`, `error_subcode` and `type` classify the
    failure; `fbtrace_id` is the opaque handle Meta support asks for. The free
    text -- `message`, `error_user_msg`, `error_data` -- is dropped, because
    that is where an echoed phone number or message body would appear.

    Never raises: a diagnostic must not be able to fail the send path it is
    diagnosing.
    """
    fingerprint: dict = {"status": response.status_code}

    try:
        body = response.json()
    except Exception:
        # Not JSON (a gateway HTML error page, say). The status is all that can
        # be said safely -- the body is unstructured and could contain anything.
        fingerprint["error_body"] = "unparseable"
        return fingerprint

    error = body.get("error") if isinstance(body, dict) else None

    if not isinstance(error, dict):
        return fingerprint

    for field in ("code", "error_subcode", "type", "fbtrace_id"):
        value = error.get(field)

        if value is None:
            continue

        # Meta already prefixes some of its own field names, so prefixing
        # unconditionally would produce `error_error_subcode`.
        key = field if field.startswith("error") else f"error_{field}"

        fingerprint[key] = value

    return fingerprint


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

            # No `phone`, and no raw body. A phone number tied to a
            # prescription delivery says "this person is a patient here and was
            # sent a prescription" -- identifiable health information, written
            # unredacted to container logs. The correlation_id JsonFormatter
            # injects already links this line to the event that caused it, which
            # is what an operator actually needs to trace a failure.
            logger.error(
                "whatsapp_send_document_failed",
                extra=_error_fingerprint(response),
            )

            raise ExternalServiceError(
                "WhatsApp document send failed"
            )

        # This fires on EVERY successful send, so it was the highest-volume
        # leak of the four: one patient phone number per prescription delivered.
        # Nothing identifying is needed here -- the caller logs prescription_id
        # and the formatter supplies correlation_id.
        logger.info("whatsapp_document_sent")

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
                extra=_error_fingerprint(response),
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
            # template_name is a configured identifier, not patient data, so
            # it stays -- it is the field that says WHICH template Meta rejected.
            # The raw body goes: this statement's own fields were already safe,
            # and the leak arrived through response.text echoing `{"to": phone}`.
            logger.error(
                "whatsapp_send_template_failed",
                extra={"template_name": template_name, **_error_fingerprint(response)},
            )

            raise ExternalServiceError("WhatsApp template send failed")

        logger.info(
            "whatsapp_template_sent",
            extra={"template_name": template_name},
        )

        return response.json()

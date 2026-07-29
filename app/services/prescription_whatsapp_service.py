import logging

from app.services.whatsapp_service import (
    WhatsAppService,
)

logger = logging.getLogger(__name__)


async def send_prescription_whatsapp(
    *,
    phone: str,
    prescription_id: int,
    pdf_bytes: bytes,
):

    logger.info(
        "sending_prescription_whatsapp",
        extra={
            "prescription_id": prescription_id,
        },
    )

    filename = (
        f"prescription_{prescription_id}.pdf"
    )

    media_id = await WhatsAppService.upload_media(
        pdf_bytes=pdf_bytes,
        filename=filename,
    )

    await WhatsAppService.send_document(
        phone=phone,
        media_id=media_id,
        filename=filename,
    )
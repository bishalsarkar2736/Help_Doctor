from app.services.email import send_email
from app.services.email_template_service import (
    render_template,
)
from app.config import get_settings
import logging

logger = logging.getLogger(__name__)
settings= get_settings()


async def send_prescription_email(
    *,
    email: str,
    prescription_id: int,
    pdf_bytes: bytes,
):
    
    logger.info(
        "mail_settings",
        extra={
            "username": settings.MAIL_USERNAME,
            "host": settings.MAIL_HOST,
            "port": settings.MAIL_PORT,
        },
    )   

    html = render_template(
        "emails/prescription_issued.html"
    )

    await send_email(
        to=email,
        subject=f"Prescription #{prescription_id}",
        body=(
            "Your prescription has been issued. "
            "The PDF is attached."
        ),
        html_body=html,
        attachments=[
            (
                f"prescription_{prescription_id}.pdf",
                pdf_bytes,
                "application/pdf",
            )
        ],
    )
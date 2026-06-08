# import aiosmtplib
# from email.message import EmailMessage

# async def send_email(to: str, subject: str, body: str):
#     msg = EmailMessage()
#     msg["From"] = "noreply@helpdoctor.com"
#     msg["To"] = to
#     msg["Subject"] = subject
#     msg.set_content(body)

#     await aiosmtplib.send(
#         msg,
#         hostname="smtp.gmail.com",
#         port=587,
#         start_tls=True,
#         username="YOUR_EMAIL",
#         password="APP_PASSWORD",
#     )

from app.config import get_settings

import aiosmtplib

from email.message import EmailMessage

import logging

logger = logging.getLogger(__name__)

settings = get_settings()


async def send_email(
    *,
    to: str,
    subject: str,
    body: str,
    html_body: str | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
):
    msg = EmailMessage()

    msg["From"] = settings.MAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject

    msg.set_content(body)

    if html_body:
        msg.add_alternative(
            html_body,
            subtype="html",
        )

    if attachments:

        for (
            filename,
            file_bytes,
            mime_type,
        ) in attachments:

            maintype, subtype = mime_type.split(
                "/",
                1,
            )

            msg.add_attachment(
                file_bytes,
                maintype=maintype,
                subtype=subtype,
                filename=filename,
            )

    try:

        logger.info(
            "smtp_config",
            extra={
                "host": settings.MAIL_HOST,
                "port": settings.MAIL_PORT,
                "username": settings.MAIL_USERNAME,
                "password_length": len(settings.MAIL_PASSWORD or ""),
                "from_email": settings.MAIL_FROM,
            },
        )

        await aiosmtplib.send(
            msg,
            hostname=settings.MAIL_HOST,
            port=settings.MAIL_PORT,
            start_tls=settings.MAIL_USE_TLS,
            username=settings.MAIL_USERNAME,
            password=settings.MAIL_PASSWORD,
        )
    
    except Exception:
        raise
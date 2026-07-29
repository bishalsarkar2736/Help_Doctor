
from app.config import get_settings

import os
import aiosmtplib

from email.message import EmailMessage
from email.utils import formataddr

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
    # Never hit a real SMTP server during tests.
    if os.getenv("TESTING") == "1":
        return

    msg = EmailMessage()

    # MAIL_FROM must stay the SMTP-authenticated address: sending as a domain
    # the server isn't authorised for (no SPF/DKIM alignment) is what lands
    # verification mail in spam. The display name is cosmetic and safe.
    msg["From"] = formataddr((settings.APP_NAME, settings.MAIL_FROM))
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

        # Only authenticate when credentials are configured. A local dev
        # catcher (MailHog/Mailpit) accepts anonymous mail and will refuse an
        # AUTH command outright, so sending empty credentials breaks it.
        auth = {}
        if settings.MAIL_USERNAME:
            auth = {
                "username": settings.MAIL_USERNAME,
                "password": settings.MAIL_PASSWORD,
            }

        await aiosmtplib.send(
            msg,
            hostname=settings.MAIL_HOST,
            port=settings.MAIL_PORT,
            start_tls=settings.MAIL_USE_TLS,
            **auth,
        )
    
    except Exception:
        logger.exception(
            "Failed to send email",
            extra={
                "to": to,
                "subject": subject,
            },
        )
        raise




async def send_password_reset_email(
    *,
    email: str,
    token: str,
) -> None:
    reset_url = (
        f"{settings.FRONTEND_URL}/reset-password?token={token}"
    )

    body = f"""
Hello,

We received a request to reset your password.

Reset your password using the link below:

{reset_url}

If you did not request this, you can safely ignore this email.

This link will expire in 1 hour.
"""

    html = f"""
<p>Hello,</p>

<p>We received a request to reset your password.</p>

<p>
    <a href="{reset_url}">
        Reset Password
    </a>
</p>

<p>
If you did not request this, you can safely ignore this email.
</p>

<p>This link expires in 1 hour.</p>
"""

    await send_email(
        to=email,
        subject="Reset your password",
        body=body,
        html_body=html,
    )



async def send_email_verification_email(
    *,
    email: str,
    token: str,
) -> None:

    verification_url = (
        f"{settings.FRONTEND_URL}"
        f"/verify-email?token={token}"
    )

    body = f"""
Hello,

Please verify your email by clicking the link below.

{verification_url}

If you did not create this account, you can safely ignore this email.

This link expires in 24 hours.
"""

    html = f"""
<p>Hello,</p>

<p>Please verify your email by clicking the link below.</p>

<p>
    <a href="{verification_url}">
        Verify Email
    </a>
</p>

<p>
If you did not create this account, you can safely ignore this email.
</p>

<p>This link expires in 24 hours.</p>
"""

    await send_email(
        to=email,
        subject="Verify your email",
        body=body,
        html_body=html,
    )


async def send_email_verification_otp(
    *,
    email: str,
    code: str,
    expires_minutes: int,
) -> None:
    """Email a one-time verification code (used at registration)."""

    body = f"""
Hello,

Your HelpDoctor verification code is:

    {code}

Enter this code to finish creating your account.
It expires in {expires_minutes} minutes.

If you did not create this account, you can safely ignore this email —
someone may have typed your address by mistake. Never share this code.
"""

    html = f"""
<p>Hello,</p>

<p>Your HelpDoctor verification code is:</p>

<p style="font-size:28px;font-weight:bold;letter-spacing:6px;margin:16px 0;">
    {code}
</p>

<p>Enter this code to finish creating your account.
It expires in {expires_minutes} minutes.</p>

<p>If you did not create this account, you can safely ignore this email —
someone may have typed your address by mistake. <strong>Never share this
code.</strong></p>
"""

    await send_email(
        to=email,
        subject=f"{code} is your HelpDoctor verification code",
        body=body,
        html_body=html,
    )


async def send_invitation_email(
    *,
    email: str,
    token: str,
    clinic_name: str,
    role: str,
) -> None:
    accept_url = (
        f"{settings.FRONTEND_URL}"
        f"/accept-invite?token={token}"
    )

    body = f"""
Hello,

You have been invited to join {clinic_name} on HelpDoctor as a {role}.

Accept your invitation and set your password using the link below:

{accept_url}

If you were not expecting this invitation, you can safely ignore this email.

This link will expire in 7 days.
"""

    html = f"""
<p>Hello,</p>

<p>You have been invited to join <strong>{clinic_name}</strong> on
HelpDoctor as a <strong>{role}</strong>.</p>

<p>
    <a href="{accept_url}">
        Accept Invitation
    </a>
</p>

<p>If you were not expecting this invitation, you can safely ignore this email.</p>

<p>This link expires in 7 days.</p>
"""

    await send_email(
        to=email,
        subject=f"You're invited to join {clinic_name}",
        body=body,
        html_body=html,
    )
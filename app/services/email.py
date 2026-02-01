import aiosmtplib
from email.message import EmailMessage

async def send_email(to: str, subject: str, body: str):
    msg = EmailMessage()
    msg["From"] = "noreply@helpdoctor.com"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    await aiosmtplib.send(
        msg,
        hostname="smtp.gmail.com",
        port=587,
        start_tls=True,
        username="YOUR_EMAIL",
        password="APP_PASSWORD",
    )

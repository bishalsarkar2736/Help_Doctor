from app.services.email import send_email
from app.services.email_template_service import (
    render_template,
)

async def send_appointment_cancel_email(
    email: str,
    cancelled_by: str,
):
    
    html = render_template(
        "emails/appointment_cancelled.html",
        cancelled_by=cancelled_by,
    )

    
    await send_email(
        to=email,
        subject="Appointment Cancelled",
        body=(
            f"Your appointment was cancelled "
            f"by {cancelled_by}."
        ),
        html_body=html,
    )
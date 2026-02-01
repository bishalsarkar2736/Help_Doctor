
from app.services.email import send_email 

async def send_appointment_cancel_email(email: str, cancelled_by: str):
    await send_email(
        email,
        "Appointment Cancelled",
        f"Your appointment was cancelled by {cancelled_by}."
    )

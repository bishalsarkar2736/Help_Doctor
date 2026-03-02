from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.appointment import Appointment


async def get_locked_appointment(
    db: AsyncSession,
    appointment_id: int,
) -> Appointment | None:
    result = await db.execute(
        select(Appointment)
        .where(Appointment.id == appointment_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.medicine_ai_feedback import (
    MedicineAIFeedback,
)


async def create_feedback(
    db: AsyncSession,
    *,
    ai_log_id: int,
    helpful: bool,
):

    feedback = MedicineAIFeedback(
        ai_log_id=ai_log_id,
        helpful=helpful,
    )

    db.add(feedback)

    await db.flush()

    await db.refresh(feedback)

    return feedback
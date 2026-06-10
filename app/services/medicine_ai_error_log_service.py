from sqlalchemy.ext.asyncio import AsyncSession

from app.models.medicine_ai_error_log import (
    MedicineAIErrorLog,
)


async def create_ai_error_log(
    db: AsyncSession,
    *,
    question: str,
    medicine_name: str | None,
    error: str,
):

    log = MedicineAIErrorLog(
        question=question,
        medicine_name=medicine_name,
        error=error,
    )

    db.add(log)

    await db.flush()

    return log
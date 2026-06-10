from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.medicine_ai_log import (
    MedicineAILog,
)

from app.models.medicine_ai_feedback import (
    MedicineAIFeedback,
)


async def create_ai_log(
    db: AsyncSession,
    *,
    medicine_id: int | None,
    medicine_name: str | None,
    question: str,
    answer: str,
    prompt_version: str,
    tokens_used: int,
    latency_ms: int,
):
    log = MedicineAILog(
        medicine_id=medicine_id,
        medicine_name=medicine_name,
        question=question,
        answer=answer,
        prompt_version=prompt_version,
        tokens_used=tokens_used,
        latency_ms=latency_ms,
    )

    db.add(log)

    await db.flush()

    await db.refresh(log)

    return log


async def get_ai_logs(
    db: AsyncSession,
    *,
    medicine_name: str | None = None,
    prompt_version: str | None = None,
    helpful: bool | None = None,
    limit: int = 50,
):

    query = (
        select(
            MedicineAILog,
            MedicineAIFeedback.helpful,
        )
        .outerjoin(
            MedicineAIFeedback,
            MedicineAIFeedback.ai_log_id
            == MedicineAILog.id,
        )
    )

    if medicine_name:
        query = query.where(
            MedicineAILog.medicine_name
            == medicine_name
        )

    if prompt_version:
        query = query.where(
            MedicineAILog.prompt_version
            == prompt_version
        )

    if helpful is not None:
        query = query.where(
            MedicineAIFeedback.helpful
            == helpful
        )

    query = (
        query.order_by(
            MedicineAILog.created_at.desc()
        )
        .limit(limit)
    )

    result = await db.execute(query)

    return [
        {
            "id": log.id,
            "medicine_name": log.medicine_name,
            "question": log.question,
            "answer": log.answer,
            "prompt_version": log.prompt_version,
            "tokens_used": log.tokens_used,
            "latency_ms": log.latency_ms,
            "helpful": helpful_value,
            "created_at": log.created_at,
        }
        for log, helpful_value in result.all()
    ]
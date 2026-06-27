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
    clinic_id : int,
    medicine_id: int | None,
    medicine_name: str | None,
    question: str,
    answer: str,
    prompt_version: str,
    tokens_used: int,
    latency_ms: int,
):


    log = MedicineAILog(
        
        clinic_id=clinic_id,

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
    clinic_id : int,
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
        .where(
            MedicineAILog.clinic_id
            == clinic_id
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


async def get_ai_log_stats(
    db: AsyncSession,
    clinic_id : int,
):


    total_queries = await db.scalar(
        select(
            func.count(
                MedicineAILog.id
            )
        ).where(
            MedicineAILog.clinic_id
            == clinic_id
        )
    )

    total_tokens = await db.scalar(
        select(
            func.coalesce(
                func.sum(
                    MedicineAILog.tokens_used
                ),
                0,
            )
        ).where(
            MedicineAILog.clinic_id
            == clinic_id
        )
    )

    avg_latency = await db.scalar(
        select(
            func.coalesce(
                func.avg(
                    MedicineAILog.latency_ms
                ),
                0,
            )
        ).where(
            MedicineAILog.clinic_id
            == clinic_id
        )
    )

    return {
        "total_queries": total_queries,
        "total_tokens": total_tokens,
        "avg_latency_ms": round(
            float(avg_latency),
            2,
        ),
    }
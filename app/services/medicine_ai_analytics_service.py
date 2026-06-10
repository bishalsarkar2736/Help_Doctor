from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.medicine_ai_log import (
    MedicineAILog,
)

from app.models.medicine_ai_error_log import (
    MedicineAIErrorLog,
)

from app.models.medicine_ai_feedback import (
    MedicineAIFeedback,
)


COST_PER_1K_TOKENS = 0.0004


async def get_total_ai_requests(
    db: AsyncSession,
) -> int:

    result = await db.execute(
        select(
            func.count(
                MedicineAILog.id
            )
        )
    )

    return result.scalar_one()


async def get_average_latency(
    db: AsyncSession,
) -> float:

    result = await db.execute(
        select(
            func.avg(
                MedicineAILog.latency_ms
            )
        )
    )

    value = result.scalar()

    return round(
        float(value or 0),
        2,
    )


async def get_prompt_versions(
    db: AsyncSession,
):

    result = await db.execute(
        select(
            MedicineAILog.prompt_version,
            func.count(
                MedicineAILog.id
            ).label("total_requests"),
            func.avg(
                MedicineAILog.latency_ms
            ).label("average_latency_ms"),
        )
        .group_by(
            MedicineAILog.prompt_version
        )
    )

    return [
        {
            "prompt_version":
            row.prompt_version,

            "total_requests":
            row.total_requests,

            "average_latency_ms":
            round(
                float(
                    row.average_latency_ms
                    or 0
                ),
                2,
            ),
        }
        for row in result
    ]


async def get_top_ai_questions(
    db: AsyncSession,
    limit: int = 20,
):

    result = await db.execute(
        select(
            MedicineAILog.question,
            func.count(
                MedicineAILog.id
            ).label("total"),
        )
        .group_by(
            MedicineAILog.question
        )
        .order_by(
            func.count(
                MedicineAILog.id
            ).desc()
        )
        .limit(limit)
    )

    return [
        {
            "question": row.question,
            "total": row.total,
        }
        for row in result
    ]


async def get_tokens_by_medicine(
    db: AsyncSession,
    limit: int = 20,
):

    result = await db.execute(
        select(
            MedicineAILog.medicine_name,
            func.sum(
                MedicineAILog.tokens_used
            ).label("tokens"),
        )
        .group_by(
            MedicineAILog.medicine_name
        )
        .order_by(
            func.sum(
                MedicineAILog.tokens_used
            ).desc()
        )
        .limit(limit)
    )

    return [
        {
            "medicine_name":
            row.medicine_name,

            "tokens":
            int(
                row.tokens or 0
            ),
        }
        for row in result
    ]


async def get_estimated_cost(
    db: AsyncSession,
):

    result = await db.execute(
        select(
            func.sum(
                MedicineAILog.tokens_used
            )
        )
    )

    total_tokens = (
        result.scalar()
        or 0
    )

    estimated_cost = (
        total_tokens / 1000
    ) * COST_PER_1K_TOKENS

    return {
        "total_tokens":
        total_tokens,

        "estimated_cost_usd":
        round(
            estimated_cost,
            4,
        ),
    }


async def get_total_ai_failures(
    db: AsyncSession,
) -> int:

    result = await db.execute(
        select(
            func.count(
                MedicineAIErrorLog.id
            )
        )
    )

    return result.scalar_one()



async def get_common_ai_errors(
    db: AsyncSession,
    limit: int = 20,
):

    result = await db.execute(
        select(
            MedicineAIErrorLog.error,
            func.count(
                MedicineAIErrorLog.id
            ).label("total"),
        )
        .group_by(
            MedicineAIErrorLog.error
        )
        .order_by(
            func.count(
                MedicineAIErrorLog.id
            ).desc()
        )
        .limit(limit)
    )

    return [
        {
            "error": row.error,
            "total": row.total,
        }
        for row in result
    ]


async def get_feedback_summary(
    db: AsyncSession,
):

    result = await db.execute(
        select(
            MedicineAIFeedback.helpful,
            func.count(
                MedicineAIFeedback.id
            ).label("total"),
        )
        .group_by(
            MedicineAIFeedback.helpful
        )
    )

    helpful = 0
    not_helpful = 0

    for row in result:

        if row.helpful:
            helpful = row.total
        else:
            not_helpful = row.total

    return {
        "helpful": helpful,
        "not_helpful": not_helpful,
    }


async def get_most_disliked_questions(
    db: AsyncSession,
    limit: int = 20,
):

    result = await db.execute(
        select(
            MedicineAILog.question,
            func.count(
                MedicineAIFeedback.id
            ).label("dislikes"),
        )
        .join(
            MedicineAILog,
            MedicineAILog.id
            == MedicineAIFeedback.ai_log_id,
        )
        .where(
            MedicineAIFeedback.helpful.is_(False)
        )
        .group_by(
            MedicineAILog.question
        )
        .order_by(
            func.count(
                MedicineAIFeedback.id
            ).desc()
        )
        .limit(limit)
    )

    return [
        {
            "question": row.question,
            "dislikes": row.dislikes,
        }
        for row in result
    ]
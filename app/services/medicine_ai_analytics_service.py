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
    clinic_id: int,
) -> int:

    result = await db.execute(
        select(
            func.count(
                MedicineAILog.id
            )
        )
        .where(
            MedicineAILog.clinic_id == clinic_id
        )
    )

    return result.scalar_one()


async def get_average_latency(
    db: AsyncSession,
    clinic_id: int,
) -> float:

    result = await db.execute(
        select(
            func.avg(
                MedicineAILog.latency_ms
            )
        )
        .where(
            MedicineAILog.clinic_id == clinic_id
        )
    )

    value = result.scalar()

    return round(
        float(value or 0),
        2,
    )


async def get_prompt_versions(
    db: AsyncSession,
    clinic_id: int,
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
        .where(
            MedicineAILog.clinic_id == clinic_id
        )
        .group_by(
            MedicineAILog.prompt_version
        )
        .order_by(
            MedicineAILog.prompt_version.desc()
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
    clinic_id: int,
    limit: int = 20,
):
    """What the assistant is asked ABOUT, most often.

    Grouped by medicine rather than by the question text, which is no longer
    stored. This is also the better signal: ten people asking about Napa in ten
    different phrasings were ten separate rows before, and are one now.
    """
    result = await db.execute(
        select(
            MedicineAILog.medicine_name,
            func.count(MedicineAILog.id).label("total"),
        )
        .where(MedicineAILog.clinic_id == clinic_id)
        .group_by(MedicineAILog.medicine_name)
        .order_by(func.count(MedicineAILog.id).desc())
        .limit(limit)
    )

    return [
        {"medicine_name": row.medicine_name, "total": row.total}
        for row in result
    ]


async def get_tokens_by_medicine(
    db: AsyncSession,
    clinic_id: int,
    limit: int = 20,
):

    result = await db.execute(
        select(
            MedicineAILog.medicine_name,
            func.sum(
                MedicineAILog.tokens_used
            ).label("tokens"),
        )
        .where(
            MedicineAILog.clinic_id == clinic_id,
            MedicineAILog.medicine_name.is_not(None),
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
    clinic_id: int,
):

    result = await db.execute(
        select(
            func.coalesce(
                func.sum(
                    MedicineAILog.tokens_used
                ),
                0,
            )
        )
        .where(
            MedicineAILog.clinic_id == clinic_id
        )
    )

    total_tokens = result.scalar_one()

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
    clinic_id : int,
) -> int:

    result = await db.execute(
        select(
            func.count(
                MedicineAIErrorLog.id
            )
        )
        .where(
            MedicineAIErrorLog.clinic_id == clinic_id
        )
    )

    return result.scalar_one()



async def get_common_ai_errors(
    db: AsyncSession,
    clinic_id : int,
    limit: int = 20,
):

    result = await db.execute(
        select(
            MedicineAIErrorLog.error,
            func.count(
                MedicineAIErrorLog.id
            ).label("total"),
        )
        .where(
            MedicineAIErrorLog.clinic_id == clinic_id
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
    clinic_id : int,
):

    result = await db.execute(
        select(
            MedicineAIFeedback.helpful,
            func.count(
                MedicineAIFeedback.id
            ).label("total"),
        )
        .join(
            MedicineAILog,
            MedicineAILog.id
            == MedicineAIFeedback.ai_log_id,
        )
        .where(
            MedicineAILog.clinic_id == clinic_id
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
    clinic_id : int,
    limit: int = 20,
):

    # Grouped by medicine, not by question text, which is no longer stored.
    # "Which medicines do our answers get wrong" is the actionable form of this
    # anyway: it points at a catalogue row to fix rather than at a phrasing.
    result = await db.execute(
        select(
            MedicineAILog.medicine_name,
            func.count(MedicineAIFeedback.id).label("dislikes"),
        )
        .join(
            MedicineAILog,
            MedicineAILog.id == MedicineAIFeedback.ai_log_id,
        )
        .where(
            MedicineAILog.clinic_id == clinic_id,
            MedicineAIFeedback.helpful.is_(False),
        )
        .group_by(MedicineAILog.medicine_name)
        .order_by(func.count(MedicineAIFeedback.id).desc())
        .limit(limit)
    )

    return [
        {"medicine_name": row.medicine_name, "dislikes": row.dislikes}
        for row in result
    ]


async def get_helpful_percentage(
    db: AsyncSession,
    clinic_id: int,
) -> float:

    summary = await get_feedback_summary(
        db,
        clinic_id
    )

    helpful = summary["helpful"]

    not_helpful = summary["not_helpful"]

    total = helpful + not_helpful

    if total == 0:
        return 0.0

    return round(
        helpful * 100 / total,
        2,
    )


async def get_failure_rate_percentage(
    db: AsyncSession,
    clinic_id: int,
) -> float:

    total_requests = await get_total_ai_requests(
        db,
        clinic_id
    )

    total_failures = await get_total_ai_failures(
        db,
        clinic_id
    )

    if total_requests == 0:
        return 0.0

    return round(
        total_failures
        * 100
        / total_requests,
        2,
    )




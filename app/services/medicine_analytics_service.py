from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.medicine_assistant_query import (
    MedicineAssistantQuery,
)


async def get_total_queries(
    db: AsyncSession,
) -> int:

    result = await db.execute(
        select(
            func.count(
                MedicineAssistantQuery.id
            )
        )
    )

    return result.scalar_one()


async def get_queries_today(
    db: AsyncSession,
) -> int:

    today = date.today()

    result = await db.execute(
        select(
            func.count(
                MedicineAssistantQuery.id
            )
        ).where(
            func.date(
                MedicineAssistantQuery.created_at
            )
            == today
        )
    )

    return result.scalar_one()


async def get_top_medicines(
    db: AsyncSession,
    limit: int = 10,
):

    result = await db.execute(
        select(
            MedicineAssistantQuery.medicine_name,
            func.count(
                MedicineAssistantQuery.id
            ).label("search_count"),
        )
        .where(
            MedicineAssistantQuery.medicine_name.is_not(
                None
            )
        )
        .group_by(
            MedicineAssistantQuery.medicine_name
        )
        .order_by(
            func.count(
                MedicineAssistantQuery.id
            ).desc()
        )
        .limit(limit)
    )

    return [
        {
            "medicine_name": row.medicine_name,
            "search_count": row.search_count,
        }
        for row in result
    ]


async def get_failed_queries(
    db: AsyncSession,
    limit: int = 20,
):
    """When the assistant could not match a question to any medicine.

    This used to list the questions themselves, which is the single largest
    exposure of patient-typed text in the product — surfaced to clinic admins,
    in plain view. The text is no longer stored.

    What it answers now is "how often are we failing, and when", which is the
    part that is actionable: a rising count means the catalogue or its aliases
    need attention. Which words were used is not needed to act on that.
    """
    result = await db.execute(
        select(
            func.date(MedicineAssistantQuery.created_at).label("day"),
            func.count(MedicineAssistantQuery.id).label("failures"),
        )
        .where(MedicineAssistantQuery.medicine_name.is_(None))
        .group_by(func.date(MedicineAssistantQuery.created_at))
        .order_by(func.date(MedicineAssistantQuery.created_at).desc())
        .limit(limit)
    )

    return [
        {"day": row.day, "failures": row.failures}
        for row in result
    ]


async def get_daily_query_counts(
    db: AsyncSession,
    days: int = 30,
):

    start_date = (
        date.today()
        - timedelta(days=days)
    )

    result = await db.execute(
        select(
            func.date(
                MedicineAssistantQuery.created_at
            ).label("day"),
            func.count(
                MedicineAssistantQuery.id
            ).label("count"),
        )
        .where(
            MedicineAssistantQuery.created_at
            >= start_date
        )
        .group_by("day")
        .order_by("day")
    )

    return [
        {
            "date": str(row.day),
            "count": row.count,
        }
        for row in result
    ]
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import extract
from app.models.outbox_event import OutboxEvent
from app.core.time import utc_now
from datetime import timedelta




async def get_outbox_overview(
    db: AsyncSession,
):
    total_events = await db.scalar(
        select(func.count())
        .select_from(OutboxEvent)
    )

    processed_events = await db.scalar(
        select(func.count())
        .select_from(OutboxEvent)
        .where(
            OutboxEvent.processed_at.is_not(None)
        )
    )

    pending_events = await db.scalar(
        select(func.count())
        .select_from(OutboxEvent)
        .where(
            OutboxEvent.processed_at.is_(None)
        )
    )

    failed_events = await db.scalar(
        select(func.count())
        .select_from(OutboxEvent)
        .where(
            OutboxEvent.failed_at.is_not(None)
        )
    )

    return {
        "total_events": total_events or 0,
        "processed_events": processed_events or 0,
        "pending_events": pending_events or 0,
        "failed_events": failed_events or 0,
    }


async def get_outbox_success_rate(
    db: AsyncSession,
):
    total = await db.scalar(
        select(func.count())
        .select_from(OutboxEvent)
    )

    processed = await db.scalar(
        select(func.count())
        .select_from(OutboxEvent)
        .where(
            OutboxEvent.processed_at.is_not(None)
        )
    )

    if not total:
        return {"success_rate": 0}

    return {
        "success_rate": round(
            processed / total,
            4,
        )
    }


async def get_outbox_queue_depth(
    db: AsyncSession,
):
    pending = await db.scalar(
        select(func.count())
        .select_from(OutboxEvent)
        .where(
            OutboxEvent.processed_at.is_(None)
        )
    )

    return {
        "queue_depth": pending or 0
    }


async def get_outbox_processing_latency(
    db: AsyncSession,
):
    result = await db.execute(
        select(
            func.avg(
                extract(
                    "epoch",
                    OutboxEvent.processed_at
                    - OutboxEvent.created_at
                )
            )
        )
        .where(
            OutboxEvent.processed_at.is_not(None)
        )
    )

    avg_seconds = result.scalar()

    return {
        "avg_processing_seconds":
            round(avg_seconds or 0, 2)
    }


async def get_outbox_failures_by_day(
    db: AsyncSession,
    days: int = 30,
):
    since = utc_now() - timedelta(days=days)

    result = await db.execute(
        select(
            func.date(OutboxEvent.failed_at),
            func.count(),
        )
        .where(
            OutboxEvent.failed_at.is_not(None),
            OutboxEvent.failed_at >= since,
        )
        .group_by(
            func.date(OutboxEvent.failed_at)
        )
        .order_by(
            func.date(OutboxEvent.failed_at)
        )
    )

    return [
        {
            "date": str(row[0]),
            "failures": row[1],
        }
        for row in result.all()
    ]
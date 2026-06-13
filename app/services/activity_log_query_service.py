from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import (
    ActivityLog,
)


async def get_activity_logs(
    db: AsyncSession,
    limit: int = 100,
    offset: int = 0,
):
    result = await db.execute(
        select(ActivityLog)
        .order_by(
            ActivityLog.id.desc()
        )
        .offset(offset)
        .limit(limit)
    )

    logs = result.scalars().all()

    return [
        {
            "id": log.id,
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "actor_id": log.actor_id,
            "details": log.details,
        }
        for log in logs
    ]
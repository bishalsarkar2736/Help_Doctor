
from datetime import datetime

from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityLog


from app.models.enums.activity_action import (
    ActivityAction,
)


async def get_activity_logs(
    *,
    db: AsyncSession,
    clinic_id : int ,
    limit: int = 100,
    offset: int = 0,
    action: str | ActivityAction | None = None,
    entity_type: str | None = None,
    actor_id: int | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
):
    


    filters = [
        ActivityLog.clinic_id == clinic_id
    ]

    if action:
        filters.append(
            ActivityLog.action == action
        )

    if entity_type:
        filters.append(
            ActivityLog.entity_type == entity_type
        )

    if actor_id is not None:
        filters.append(
            ActivityLog.actor_id == actor_id
        )

    if start_date:
        filters.append(
            ActivityLog.created_at >= start_date
        )

    if end_date:
        filters.append(
            ActivityLog.created_at <= end_date
        )

    stmt = (
        select(ActivityLog)
        .where(*filters)
        .order_by(
            ActivityLog.created_at.desc()
        )
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(stmt)

    logs = result.scalars().all()

    count_result = await db.execute(
        select(
            func.count(ActivityLog.id)
        ).where(*filters)
    )

    total_count = count_result.scalar_one()

    return {
        "items": logs,
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "has_next": (
            offset + limit
        ) < total_count,
    }
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import (
    ActivityLog,
)


async def log_activity(
    *,
    db: AsyncSession,
    actor_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    details: str | None = None,
):

    db.add(
        ActivityLog(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
        )
    )
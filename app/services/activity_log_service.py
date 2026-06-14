from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import (
    ActivityLog,
)
from app.services.clinic_context_service import (
    get_current_clinic,
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
    
    clinic = await get_current_clinic(db)

    db.add(
        ActivityLog(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            clinic_id=clinic.id,
        )
    )
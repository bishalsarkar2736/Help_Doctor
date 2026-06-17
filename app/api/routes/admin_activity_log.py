from fastapi import (
    APIRouter,
    Depends,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from app.db.postgres import (
    get_db,
)
from app.services.activity_log_query_service import (
    get_activity_logs,
)
from app.security.rbac import require_roles
from app.models.user import (
    User,
    UserRole,
)
from datetime import datetime
from app.schemas.activity_log_schema import (
    ActivityLogListResponse,
)


router = APIRouter(
    prefix="/activity/log",
    tags=["activity log"],
)


@router.get(
    "/",
    response_model=ActivityLogListResponse,
)
async def list_activity_logs(
    limit: int = 100,
    offset: int = 0,

    action: str | None = None,
    entity_type: str | None = None,
    actor_id: int | None = None,

    start_date: datetime | None = None,
    end_date: datetime | None = None,

    db: AsyncSession = Depends(get_db),

    admin: User = Depends(
        require_roles(UserRole.ADMIN)
    ),
):

    return await get_activity_logs(
        db=db,
        limit=limit,
        offset=offset,
        action=action,
        entity_type=entity_type,
        actor_id=actor_id,
        start_date=start_date,
        end_date=end_date,
    )
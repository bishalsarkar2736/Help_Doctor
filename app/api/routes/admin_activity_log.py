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

router = APIRouter(
    prefix="/activity/log",
    tags=["activity log"],
)


@router.get("/")
async def list_activity_logs(
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(
        get_db
    ),
    admin: User = Depends(
        require_roles(
            UserRole.ADMIN
        )
    ),
):

    return await get_activity_logs(
        db=db,
        limit=limit,
        offset=offset,
    )
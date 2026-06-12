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

from app.models.user import (
    UserRole,
)

from app.security.rbac import (
    require_roles,
)

from app.services.dashboard_service import (
    get_dashboard_data,
)

router = APIRouter(
    prefix="/admin",
    tags=["Dashboard"],
)


@router.get("/dashboard")
async def dashboard(
    db: AsyncSession = Depends(get_db),
    admin=Depends(
        require_roles(
            UserRole.ADMIN,
        )
    ),
):
    return await get_dashboard_data(
        db=db,
    )
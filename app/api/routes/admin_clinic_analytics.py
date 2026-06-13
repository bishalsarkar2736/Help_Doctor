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
    User
)

from app.security.rbac import (
    require_roles,
)

from app.services.clinic_analytics_service import (
    get_clinic_analytics,
)

router = APIRouter(
    prefix="/admin/clinic",
    tags=["Clinic Analytics"],
)


@router.get("/analytics")
async def clinic_analytics(
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(
            UserRole.ADMIN
        )
    ),
):

    return await get_clinic_analytics(
        db=db,
    )
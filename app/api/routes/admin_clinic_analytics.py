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

from app.services.tenant_resolver import resolve_clinic_id


router = APIRouter(
    prefix="/admin/clinic",
    tags=["Clinic Analytics"],
)


@router.get("/analytics")
async def clinic_analytics(
    clinic_id : int,
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(
            UserRole.ADMIN
        )
    ),
):
    
    resolved_clinic_id = await resolve_clinic_id(
        db=db,
        user=admin,
        clinic_id=clinic_id,
    )

    return await get_clinic_analytics(
        db=db,
        clinic_id=resolved_clinic_id,
    )
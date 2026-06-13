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

from app.services.appointment_analytics_service import (
    get_appointment_analytics,
)

router = APIRouter(
    prefix="/admin/analytics",
    tags=["Appointment Analytics"],
)


@router.get("/appointments")
async def appointment_analytics(
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(
            UserRole.ADMIN
        )
    ),
):

    return await get_appointment_analytics(
        db=db,
    )
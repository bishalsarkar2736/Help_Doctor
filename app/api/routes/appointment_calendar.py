from datetime import date

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
    UserRole,User
)

from app.security.rbac import (
    require_roles,
)

from app.services.appointment_calendar_service import (
    get_calendar_appointments,
)
from app.services.tenant_resolver import resolve_clinic_id


router = APIRouter(
    prefix="/appointments",
    tags=["Appointment Calendar"],
)


@router.get("/calendar")
async def appointment_calendar(
    start_date: date,
    end_date: date,
    doctor_id: int | None = None,
    clinic_id: int | None = None,
    db: AsyncSession = Depends(
        get_db
    ),
    user : User =Depends(
        require_roles(
            UserRole.ADMIN,
            UserRole.DOCTOR,
        )
    ),
):

    resolved_clinic_id = await resolve_clinic_id(
        db=db,
        user=user,
        clinic_id=clinic_id,
    )

    return await get_calendar_appointments(
        db=db,
        clinic_id=resolved_clinic_id,
        start_date=start_date,
        end_date=end_date,
        doctor_id=doctor_id,
    )
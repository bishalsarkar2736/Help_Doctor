from datetime import date

from fastapi import (
    APIRouter,
    Depends,
)
from sqlalchemy import select

from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from app.db.postgres import (
    get_db,
)

from app.models.user import (
    UserRole,User
)
from app.models.doctor import Doctor

from app.security.rbac import (
    require_roles,
)
from app.try_except.exceptions import ForbiddenError

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
    
    if user.role == UserRole.DOCTOR:

        result = await db.execute(
            select(Doctor).where(
                Doctor.user_id == user.id
            )
        )

        doctor = result.scalar_one_or_none()

        if not doctor:
            raise ForbiddenError(
                "Doctor profile not found"
            )

        clinic_id = doctor.clinic_id

    else:  # ADMIN

        clinic_id = user.clinic_id
    


    return await get_calendar_appointments(
        db=db,
        clinic_id=clinic_id,
        start_date=start_date,
        end_date=end_date,
        doctor_id=doctor_id,
    )
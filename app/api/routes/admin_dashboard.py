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

from app.services.dashboard_service import (
    get_dashboard_data,
)

from app.schemas.top_doctors_schema import TopDoctorsResponse
from app.services.top_doctors_service import get_top_doctors

from app.schemas.clinic_kpi_schema import (
    ClinicKPIResponse,
)

from app.services.clinic_kpi_service import (
    get_clinic_kpi_dashboard,
)

from app.services.appointment_status_analytics_service import (
    get_appointment_status_distribution,
)

from app.services.doctor_analytics_service import (
    get_top_doctors_by_appointments,
    get_top_doctors_by_completed_consultations,
)

from app.services.followup_analytics_service import (
    get_followup_analytics,
)

from app.services.doctor_performance_service import (
    get_doctor_performance_scorecard,
)

from app.services.clinic_growth_service import get_growth_dashboard



router = APIRouter(
    prefix="/admin",
    tags=["Dashboard"],
)


@router.get("/dashboard")
async def dashboard(
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(
            UserRole.ADMIN,
        )
    ),
):
    return await get_dashboard_data(
        db=db,
    )


@router.get(
    "/top-doctors",
    response_model=TopDoctorsResponse,
)
async def top_doctors(
    limit: int = 5,
    db: AsyncSession = Depends(get_db),

    admin: User = Depends(
        require_roles(
            UserRole.ADMIN
        )
    ),
):
    return await get_top_doctors(
        db=db,
        limit=limit,
    )




@router.get(
    "/kpi-dashboard",
    response_model=ClinicKPIResponse,
)
async def clinic_kpi_dashboard(
    db: AsyncSession = Depends(get_db),
    admin=Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await get_clinic_kpi_dashboard(
        db=db,
    )





@router.get("/growth-dashboard")
async def growth_dashboard(
    db: AsyncSession = Depends(get_db),
    admin=Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await get_growth_dashboard(
        db=db,
    )



@router.get("/top-doctors-by-appointments")
async def top_doctors_by_appointments(
    db: AsyncSession = Depends(get_db),
    admin=Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await get_top_doctors_by_appointments(
        db=db
    )


@router.get(
    "/appointment-status-distribution"
)
async def appointment_status_distribution(
    db: AsyncSession = Depends(get_db),
    admin=Depends(
        require_roles(
            UserRole.ADMIN
        )
    ),
):
    return await get_appointment_status_distribution(
        db=db
    )



@router.get(
    "/top-doctors-by-completed-consultations"
)
async def top_doctors_by_completed_consultations(
    db: AsyncSession = Depends(get_db),
    admin=Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await (
        get_top_doctors_by_completed_consultations(
            db=db
        )
    )


@router.get(
    "/followup-analytics"
)
async def followup_analytics(
    db: AsyncSession = Depends(get_db),
    admin=Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await get_followup_analytics(
        db=db
    )


@router.get(
    "/doctor-performance-scorecard"
)
async def doctor_performance_scorecard(
    db: AsyncSession = Depends(get_db),
    admin=Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await (
        get_doctor_performance_scorecard(
            db=db
        )
    )
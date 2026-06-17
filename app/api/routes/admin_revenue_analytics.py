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

from app.services.revenue_analytics_service import (
    get_revenue_analytics,
    get_monthly_revenue,
)
from app.schemas.doctor_revenue_schema import DoctorRevenueDashboardResponse
from app.services.doctor_revenue_dashboard_service import get_doctor_revenue_dashboard
from app.services.revenue_by_specialization_service import (
    get_revenue_by_specialization,
)

from app.schemas.revenue_by_specialization_schema import (
    RevenueBySpecializationResponse,
)



router = APIRouter(
    prefix="/admin/analytics",
    tags=["Revenue Analytics"],
)


@router.get(
    "/doctor-revenue",
    response_model=DoctorRevenueDashboardResponse,
)
async def doctor_revenue_dashboard(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await get_doctor_revenue_dashboard(
        db=db,
    )



@router.get("/revenue")
async def revenue_analytics(
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(
            UserRole.ADMIN
        )
    ),
):

    return await get_revenue_analytics(
        db=db,
    )


@router.get("/revenue/monthly")
async def monthly_revenue(
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(
            UserRole.ADMIN
        )
    ),
):
    return await get_monthly_revenue(
        db=db,
    )


@router.get(
    "/revenue-by-specialization",
    response_model=list[
        RevenueBySpecializationResponse
    ],
)
async def revenue_by_specialization(
    db: AsyncSession = Depends(get_db),
    admin=Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await get_revenue_by_specialization(
        db=db,
    )
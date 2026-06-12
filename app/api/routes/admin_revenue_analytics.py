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

from app.services.revenue_analytics_service import (
    get_revenue_analytics,
)

from app.services.revenue_analytics_service import (
    get_monthly_revenue,
)

router = APIRouter(
    prefix="/admin/analytics",
    tags=["Revenue Analytics"],
)


@router.get("/revenue")
async def revenue_analytics(
    db: AsyncSession = Depends(get_db),
    admin=Depends(
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
    admin=Depends(
        require_roles(
            UserRole.ADMIN
        )
    ),
):
    return await get_monthly_revenue(
        db=db,
    )
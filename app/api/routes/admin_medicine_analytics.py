from fastapi import (
    APIRouter,
    Depends,
)

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db

from app.models.user import UserRole,User

from app.security.rbac import (
    require_roles,
)

from app.schemas.medicine_analytics_schema import (
    MedicineAnalyticsResponse,
)

from app.services.medicine_analytics_service import (
    get_daily_query_counts,
    get_failed_queries,
    get_queries_today,
    get_top_medicines,
    get_total_queries,
)

router = APIRouter(
    prefix="/admin/medicine-assistant",
    tags=["Medicine Analytics"],
)


@router.get(
    "/analytics",
    response_model=
    MedicineAnalyticsResponse,
)
async def medicine_analytics(
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(
            UserRole.ADMIN
        )
    ),
):

    return {
        "total_queries":
        await get_total_queries(db),

        "queries_today":
        await get_queries_today(db),

        "top_medicines":
        await get_top_medicines(db),

        "failed_queries":
        await get_failed_queries(db),

        "daily_query_counts":
        await get_daily_query_counts(db),
    }
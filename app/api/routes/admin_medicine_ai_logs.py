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

from app.schemas.medicine_ai_log_schema import (
    MedicineAILogStatsResponse,
)

from app.services.medicine_ai_log_service import (
    get_ai_logs,
    get_ai_log_stats,
)
from app.services.tenant_resolver import resolve_clinic_id



router = APIRouter(
    prefix="/admin/medicine-ai-logs",
    tags=["Medicine AI Logs"],
)


@router.get("")
async def list_ai_logs(
    clinic_id : int,
    medicine_name: str | None = None,
    prompt_version: str | None = None,
    helpful: bool | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    
    resolved_clinic_id = await resolve_clinic_id(
        db=db,
        user=admin,
        clinic_id=clinic_id,
    )

    return await get_ai_logs(
        db=db,
        clinic_id=resolved_clinic_id,
        medicine_name=medicine_name,
        prompt_version=prompt_version,
        helpful=helpful,
        limit=limit,
    )


@router.get(
    "/stats",
    response_model=
    MedicineAILogStatsResponse,
)
async def ai_log_stats(
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

    return await get_ai_log_stats(
        db=db,
        clinic_id=resolved_clinic_id
    )

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

from app.services.patient_history_service import (
    get_patient_history,
)
from app.schemas.patient_history_schema import PatientHistoryResponse
from app.services.tenant_resolver import resolve_clinic_id


router = APIRouter(
    prefix="/patients",
    tags=["Patient History"],
)


@router.get(
    "/{patient_id}/history",
    response_model=PatientHistoryResponse,
)
async def patient_history(
    patient_user_id: int,
    clinic_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user : User =Depends(
        require_roles(
            UserRole.ADMIN,
            UserRole.DOCTOR,
        )
    ),
):
    
    clinic_id = await resolve_clinic_id(
        db=db,
        user=user,
        clinic_id=clinic_id,
    )
    
    return await get_patient_history(
        db=db,
        clinic_id=clinic_id,
        patient_id=patient_user_id,
        limit=limit,
        offset=offset,
    )

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
from app.models.phi_access_log import PHIAction, PHIResourceType
from app.services.phi_access_log_service import log_phi_access


router = APIRouter(
    prefix="/patients",
    tags=["Patient History"],
)


@router.get(
    "/{patient_id}/history",
    response_model=PatientHistoryResponse,
)
async def patient_history(
    # MUST match the {patient_id} placeholder in the route path. It was named
    # patient_user_id, so FastAPI never bound the path segment and instead
    # demanded a query parameter of that name — the endpoint returned 422 for
    # every well-formed call and was effectively unreachable. No frontend code
    # and no test exercised it, which is why it went unnoticed.
    patient_id: int,
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
    
    history = await get_patient_history(
        db=db,
        clinic_id=clinic_id,
        patient_id=patient_id,
        limit=limit,
        offset=offset,
    )

    # The clinical record: past visits, diagnoses and prescriptions. The single
    # most sensitive read in the system.
    await log_phi_access(
        db=db,
        actor=user,
        patient_id=patient_id,
        resource_type=PHIResourceType.MEDICAL_HISTORY,
        action=PHIAction.VIEW,
        clinic_id=clinic_id,
    )

    return history
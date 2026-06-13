
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

from app.services.patient_history_service import (
    get_patient_history,
)

router = APIRouter(
    prefix="/patients",
    tags=["Patient History"],
)


@router.get("/{patient_id}/history")
async def patient_history(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(
        require_roles(
            UserRole.ADMIN,
            UserRole.DOCTOR,
        )
    ),
):
    return await get_patient_history(
        db=db,
        patient_id=patient_id,
    )
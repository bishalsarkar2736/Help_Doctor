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

from app.schemas.clinic_schema import (
    ClinicResponse,
    ClinicUpdate,
)

from app.services.clinic_service import (
    get_clinic_by_id,
    update_clinic,
)
from app.try_except.exceptions import NotFoundError
from app.services.tenant_resolver import resolve_clinic_id


router = APIRouter(
    prefix="/admin/clinic",
    tags=["Clinic"],
)



@router.get(
    "",
    response_model=ClinicResponse,
)
async def get_clinic_settings(
    clinic_id: int,
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(
            UserRole.ADMIN
        )
    ),
):

    clinic = await get_clinic_by_id(
        db=db,
        clinic_id=clinic_id,
    )

    if clinic is None:
        raise NotFoundError(
            "Clinic not found"
        )

    return clinic



@router.put(
    "",
    response_model=ClinicResponse,
)
async def update_clinic_settings(
     clinic_id: int,
    payload: ClinicUpdate,
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

    return await update_clinic(
        db=db,
        clinic_id=resolved_clinic_id,
        payload=payload,
    )

    
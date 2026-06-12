from fastapi import (
    APIRouter,
    Depends,
)

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db

from app.models.user import UserRole

from app.security.rbac import (
    require_roles,
)

from app.schemas.clinic_schema import (
    ClinicResponse,
    ClinicUpdate,
)

from app.services.clinic_service import (
    get_clinic,
    update_clinic,
)

router = APIRouter(
    prefix="/admin/clinic",
    tags=["Clinic"],
)



@router.get(
    "",
    response_model=ClinicResponse,
)
async def get_clinic_settings(
    db: AsyncSession = Depends(get_db),
    admin=Depends(
        require_roles(
            UserRole.ADMIN
        )
    ),
):

    clinic = await get_clinic(db)

    if clinic is None:

        return {
            "id": 0,
            "name": "",
            "logo_url": None,
            "address": None,
            "phone": None,
            "email": None,
            "website": None,
            "primary_color": None,
        }

    return clinic



@router.put(
    "",
    response_model=ClinicResponse,
)
async def update_clinic_settings(
    payload: ClinicUpdate,
    db: AsyncSession = Depends(get_db),
    admin=Depends(
        require_roles(
            UserRole.ADMIN
        )
    ),
):

    clinic = await update_clinic(
        db=db,
        payload=payload,
    )

    return clinic
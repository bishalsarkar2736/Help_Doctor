from fastapi import (
    APIRouter,
    Depends,
    File,
    UploadFile,
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

from app.services.clinic_logo_service import (
    upload_clinic_logo,
)
from app.services.tenant_resolver import resolve_clinic_id


router = APIRouter(
    prefix="/admin/clinic",
    tags=["Clinic"],
)


@router.post("/logo")
async def upload_logo(
    clinic_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(
            UserRole.ADMIN
        )
    ),
):
    
    clinic_id = await resolve_clinic_id(
        db=db,
        user=admin,
        clinic_id=clinic_id,
    )

    return await upload_clinic_logo(
        db=db,
        clinic_id=clinic_id,
        file=file,
    )
from fastapi import (
    APIRouter,
    Depends,
)

from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from app.db.postgres import get_db

from app.models.user import (
    UserRole,
)

from app.security.rbac import (
    require_roles,
)

from app.services.prescription_template_service import (
    create_prescription_template,
    list_prescription_templates,
    get_prescription_template,
)


from app.schemas.prescription_template_schema import (
    PrescriptionTemplateCreate,
)

from app.services.prescription_template_apply_service import (
    apply_prescription_template,
)



router = APIRouter(
    prefix="/prescription-templates",
    tags=["Prescription Templates"],
)


@router.post("/")
async def create_template(
    data: PrescriptionTemplateCreate,
    db: AsyncSession = Depends(get_db),
    doctor=Depends(
        require_roles(
            UserRole.DOCTOR,
        )
    ),
):

    return await create_prescription_template(
        db=db,
        doctor_id=doctor.doctor.id,
        data=data,
    )


@router.get("/")
async def get_templates(
    db: AsyncSession = Depends(get_db),
    doctor=Depends(
        require_roles(
            UserRole.DOCTOR,
        )
    ),
):

    return await list_prescription_templates(
        db=db,
        doctor_id=doctor.doctor.id,
    )


@router.get("/{template_id}")
async def get_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    doctor=Depends(
        require_roles(
            UserRole.DOCTOR,
        )
    ),
):

    return await get_prescription_template(
        db=db,
        template_id=template_id,
        doctor_id=doctor.doctor.id,
    )


@router.post(
    "/{template_id}/apply"
)
async def apply_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    doctor=Depends(
        require_roles(
            UserRole.DOCTOR,
        )
    ),
):

    return await apply_prescription_template(
        db=db,
        template_id=template_id,
        doctor_id=doctor.doctor.id,
    )
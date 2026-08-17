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

from app.schemas.medicine_schema import (
    MedicineCreate,
    MedicineUpdate,
    MedicineResponse,
)

from app.services.admin_medicine_service import (
    create_medicine,
    update_medicine,
    delete_medicine,
    list_medicines,
    get_medicine,
)

router = APIRouter(
    prefix="/admin/medicines",
    tags=["Admin Medicines"],
)


@router.post(
    "",
    response_model=MedicineResponse,
)
async def create_medicine_endpoint(
    payload: MedicineCreate,
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.SUPER_ADMIN)
    ),
):
    return await create_medicine(
        db,
        payload,
    )


@router.get(
    "",
    response_model=list[MedicineResponse],
)
async def list_medicines_endpoint(
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await list_medicines(db)


@router.get(
    "/{medicine_id}",
    response_model=MedicineResponse,
)
async def get_medicine_endpoint(
    medicine_id: int,
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await get_medicine(
        db,
        medicine_id,
    )


@router.put(
    "/{medicine_id}",
    response_model=MedicineResponse,
)
async def update_medicine_endpoint(
    medicine_id: int,
    payload: MedicineUpdate,
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.SUPER_ADMIN)
    ),
):
    return await update_medicine(
        db,
        medicine_id,
        payload,
    )


@router.delete("/{medicine_id}")
async def delete_medicine_endpoint(
    medicine_id: int,
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.SUPER_ADMIN)
    ),
):
    return await delete_medicine(
        db,
        medicine_id,
    )
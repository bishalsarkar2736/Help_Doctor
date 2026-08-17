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

from app.schemas.medicine_alias_schema import (
    MedicineAliasCreate,
    MedicineAliasResponse,
)

from app.services.admin_medicine_alias_service import (
    create_alias,
    delete_alias,
    list_aliases,
)


router = APIRouter(
    prefix="/admin/medicine-aliases",
    tags=["Admin Medicine Aliases"],
)


@router.post(
    "",
    response_model=
    MedicineAliasResponse,
)
async def create_alias_endpoint(
    payload: MedicineAliasCreate,
    db: AsyncSession = Depends(get_db),
    admin : User=Depends(
        require_roles(
            UserRole.SUPER_ADMIN
        )
    ),
):

    alias = await create_alias(
        db,
        payload,
    )

    await db.commit()

    return alias


@router.get(
    "",
    response_model=
    list[MedicineAliasResponse],
)
async def list_aliases_endpoint(
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(
            UserRole.ADMIN
        )
    ),
):

    return await list_aliases(
        db,
    )


@router.delete(
    "/{alias_id}",
)
async def delete_alias_endpoint(
    alias_id: int,
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(
            UserRole.SUPER_ADMIN
        )
    ),
):

    await delete_alias(
        db,
        alias_id,
    )

    await db.commit()

    return {
        "message":
        "Alias deleted successfully"
    }
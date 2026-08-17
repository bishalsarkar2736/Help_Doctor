from fastapi import APIRouter, Depends

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db

from app.models.user import User, UserRole

from app.security.rbac import require_roles

from app.schemas.generic_alias_schema import (
    GenericAliasCreate,
    GenericAliasResponse,
)

from app.services.admin_generic_alias_service import (
    create_generic_alias,
    delete_generic_alias,
    list_generic_aliases,
)


router = APIRouter(
    prefix="/admin/generic-aliases",
    tags=["Admin Generic Aliases"],
)


def _to_response(alias) -> GenericAliasResponse:
    return GenericAliasResponse(
        id=alias.id,
        generic_id=alias.generic_id,
        alias=alias.alias,
        generic_name=alias.generic.name if alias.generic else None,
    )


@router.post("", response_model=GenericAliasResponse)
async def create_generic_alias_endpoint(
    payload: GenericAliasCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.SUPER_ADMIN)),
):
    alias = await create_generic_alias(db, payload)

    await db.commit()

    # Reloaded through the listing path so the response carries the substance
    # name; the created object's relationship is not populated.
    await db.refresh(alias, attribute_names=["generic"])

    return _to_response(alias)


@router.get("", response_model=list[GenericAliasResponse])
async def list_generic_aliases_endpoint(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    return [_to_response(alias) for alias in await list_generic_aliases(db)]


@router.delete("/{alias_id}")
async def delete_generic_alias_endpoint(
    alias_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.SUPER_ADMIN)),
):
    await delete_generic_alias(db, alias_id)

    await db.commit()

    return {"message": "Alias deleted successfully"}

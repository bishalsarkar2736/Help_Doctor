from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.medicine import Medicine
from app.models.medicine_alias import MedicineAlias

from app.schemas.medicine_alias_schema import (
    MedicineAliasCreate,
)

from app.try_except.exceptions import (
    NotFoundError,BadRequestError
)



from sqlalchemy import select



async def create_alias(
    db: AsyncSession,
    payload: MedicineAliasCreate,
) -> MedicineAlias:

    medicine = await db.get(
        Medicine,
        payload.medicine_id,
    )

    if not medicine:
        raise NotFoundError(
            "Medicine not found"
        )

    normalized_alias = (
        payload.alias
        .strip()
        .lower()
    )

    existing = await db.execute(
        select(MedicineAlias)
        .where(
            MedicineAlias.medicine_id
            == payload.medicine_id,
            MedicineAlias.alias
            == normalized_alias,
        )
    )

    if existing.scalar_one_or_none():
        raise BadRequestError(
            "Alias already exists"
        )

    alias = MedicineAlias(
        medicine_id=payload.medicine_id,
        alias=normalized_alias,
    )

    db.add(alias)

    await db.flush()

    await db.refresh(alias)

    return alias



async def list_aliases(
    db: AsyncSession,
):

    result = await db.execute(
        select(MedicineAlias)
        .order_by(
            MedicineAlias.alias
        )
    )

    return (
        result.scalars()
        .unique()
        .all()
    )



async def delete_alias(
    db: AsyncSession,
    alias_id: int,
):

    alias = await db.get(
        MedicineAlias,
        alias_id,
    )

    if not alias:
        raise NotFoundError(
            "Alias not found"
        )

    await db.delete(alias)
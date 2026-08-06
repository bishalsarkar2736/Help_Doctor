"""Registering that two names denote the same active substance.

Kept deliberately manual. An alias is a clinical claim — asserting that
Acetaminophen is Paracetamol changes which prescriptions get blocked — and
deriving it from string similarity is exactly the guess that could attach the
wrong substance to a prescription and suppress a real warning.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.generic import Generic
from app.models.generic_alias import GenericAlias
from app.schemas.generic_alias_schema import GenericAliasCreate
from app.services.generic_service import normalize_generic_name
from app.try_except.exceptions import BadRequestError, NotFoundError


async def create_generic_alias(
    db: AsyncSession,
    payload: GenericAliasCreate,
) -> GenericAlias:
    generic = await db.get(Generic, payload.generic_id)

    if not generic:
        raise NotFoundError("Generic not found")

    normalized = normalize_generic_name(payload.alias)

    if not normalized:
        raise BadRequestError("Alias must contain a name")

    # An alias identical to the substance's own name adds nothing and would
    # make the allergy check run the same comparison twice.
    if normalized == generic.normalized_name:
        raise BadRequestError(
            "That is already the name of this substance."
        )

    existing = await db.scalar(
        select(GenericAlias).where(
            GenericAlias.generic_id == payload.generic_id,
            GenericAlias.normalized_alias == normalized,
        )
    )

    if existing:
        raise BadRequestError("This alias is already registered.")

    # The same name must not denote two different substances: an allergy to it
    # would then resolve to both, and the allergy check would flag medicines
    # the patient has no recorded reaction to.
    clash = await db.scalar(
        select(GenericAlias).where(
            GenericAlias.normalized_alias == normalized,
            GenericAlias.generic_id != payload.generic_id,
        )
    )

    if clash:
        raise BadRequestError(
            "That name is already registered against a different substance."
        )

    alias = GenericAlias(
        generic_id=payload.generic_id,
        alias=payload.alias.strip(),
        normalized_alias=normalized,
    )

    db.add(alias)
    await db.flush()

    return alias


async def list_generic_aliases(db: AsyncSession) -> list[GenericAlias]:
    result = await db.execute(
        select(GenericAlias)
        # selectinload: the response names the substance, and a lazy load here
        # would raise MissingGreenlet under async.
        .options(selectinload(GenericAlias.generic))
        .order_by(GenericAlias.generic_id, GenericAlias.alias)
    )

    return list(result.scalars().all())


async def delete_generic_alias(db: AsyncSession, alias_id: int) -> None:
    alias = await db.get(GenericAlias, alias_id)

    if not alias:
        raise NotFoundError("Alias not found")

    await db.delete(alias)

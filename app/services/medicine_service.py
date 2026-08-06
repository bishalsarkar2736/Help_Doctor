from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generic import Generic
from app.models.generic_alias import GenericAlias
from app.models.medicine import Medicine
from app.models.medicine_alias import MedicineAlias
from app.db.redis import get_redis



CACHE_TTL = 86400


async def get_medicine_by_name(
    db: AsyncSession,
    medicine_name: str,
):

    redis = await get_redis()

    cache_key = (
        f"medicine:{medicine_name.lower()}"
    )

    cached = await redis.get(cache_key)

    if cached:
        import json

        return json.loads(cached)

    result = await db.execute(
        select(Medicine)
        .where(
            Medicine.name.ilike(
                medicine_name
            )
        )
    )

    medicine = result.scalar_one_or_none()

    if not medicine:
        return None

    payload = {
        "id": medicine.id,
        "name": medicine.name,
        "generic_name": medicine.generic_name,
        "strength" : medicine.strength,
        "manufacturer": medicine.manufacturer,
        "category": medicine.category,
        "dosage_form": medicine.dosage_form,
        "common_use": medicine.common_use,
        "common_side_effects":
            medicine.common_side_effects,
        "storage_guidance":
            medicine.storage_guidance,
        "is_brand": medicine.is_brand,
    }

    import json

    await redis.set(
        cache_key,
        json.dumps(payload),
        ex=CACHE_TTL,
    )

    return payload


async def search_medicines(
    db: AsyncSession,
    query: str,
    limit: int = 20,
):
    """Medicines matching `query` by brand name, active substance, or alias.

    Searching the substance matters for prescribing: a doctor who types
    "Cefixime" means any of its eleven brands, and matching brand names alone
    returned none of them. Aliases cover local trade names and the spellings
    that never quite match.

    Ordered so a name that STARTS with the query comes first — typing "Cef"
    should surface "Cefim" ahead of a medicine that merely contains "cef"
    somewhere in its generic. Ties break on name for a stable list, which
    matters when the user is arrowing down it.
    """
    pattern = f"%{query}%"

    starts_with = Medicine.name.ilike(f"{query}%")

    result = await db.execute(
        select(Medicine)
        .outerjoin(Generic, Medicine.generic_id == Generic.id)
        .where(
            or_(
                Medicine.name.ilike(pattern),
                Generic.name.ilike(pattern),
                Medicine.id.in_(
                    select(MedicineAlias.medicine_id).where(
                        MedicineAlias.alias.ilike(pattern)
                    )
                ),
                # Substance aliases: a prescriber who types "Acetaminophen"
                # means every Paracetamol brand, and the catalogue files none
                # of them under that name.
                Medicine.generic_id.in_(
                    select(GenericAlias.generic_id).where(
                        GenericAlias.alias.ilike(pattern)
                    )
                ),
            )
        )
        # DISTINCT is not needed: the outer join is many-to-one and the alias
        # match is a subquery, so a medicine cannot appear twice.
        .order_by(starts_with.desc(), Medicine.name)
        .limit(limit)
    )

    return result.scalars().all()


async def get_existing_medicine_names(
    db,
    medicine_names: list[str],
) -> set[str]:

    if not medicine_names:
        return set()

    result = await db.execute(
        select(Medicine.name).where(
            Medicine.name.in_(medicine_names)
        )
    )

    return {
        name.lower()
        for name in result.scalars().all()
    }



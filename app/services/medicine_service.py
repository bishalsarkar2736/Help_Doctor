from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.medicine import Medicine
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

    result = await db.execute(
        select(Medicine)
        .where(
            Medicine.name.ilike(
                f"%{query}%"
            )
        )
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



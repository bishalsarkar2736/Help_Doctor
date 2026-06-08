from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.medicine import Medicine
from app.models.medicine_alias import MedicineAlias
from app.core.cache import get_cache,set_cache


async def match_medicine(
    db: AsyncSession,
    question: str,
) -> Medicine | None:

    question_lower = question.lower().strip()

    cache_key = (
        f"medicine_match:"
        f"{question_lower}"
    )

    cached_medicine_id = await get_cache(
        cache_key
    )

    if cached_medicine_id:

        if cached_medicine_id == "NOT_FOUND":
            return None

        result = await db.execute(
            select(Medicine).where(
                Medicine.id == cached_medicine_id
            )
        )

        return result.scalar_one_or_none()

    matches: list[tuple[int, int]] = []

    # =========================
    # MEDICINE NAME MATCHES
    # =========================

    result = await db.execute(
        select(
            Medicine.id,
            Medicine.name,
            Medicine.strength,
        )
    )

    medicines = result.all()

    for medicine_id, name, strength in medicines:

        medicine_name = name.lower()

        if medicine_name in question_lower:

            matches.append(
                (
                    len(medicine_name),
                    medicine_id,
                )
            )

        if strength:

            full_name = (
                f"{name} {strength}"
            ).lower()

            if full_name in question_lower:

                matches.append(
                    (
                        len(full_name),
                        medicine_id,
                    )
                )

    # =========================
    # ALIAS MATCHES
    # =========================

    result = await db.execute(
        select(
            MedicineAlias.alias,
            MedicineAlias.medicine_id,
        )
    )

    aliases = result.all()

    for alias, medicine_id in aliases:

        alias_lower = alias.lower()

        if alias_lower in question_lower:

            matches.append(
                (
                    len(alias_lower),
                    medicine_id,
                )
            )

    # =========================
    # NO MATCH
    # =========================

    if not matches:

        await set_cache(
            cache_key,
            "NOT_FOUND",
            ttl=3600,
        )

        return None

    # =========================
    # LONGEST MATCH WINS
    # =========================

    matches.sort(
        reverse=True
    )

    matched_medicine_id = matches[0][1]

    await set_cache(
        cache_key,
        matched_medicine_id,
        ttl=3600,
    )

    result = await db.execute(
        select(Medicine)
        .where(
            Medicine.id
            == matched_medicine_id
        )
    )

    return result.scalar_one_or_none()
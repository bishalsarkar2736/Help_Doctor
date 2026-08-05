"""Resolving a typed medicine name to its catalogue entry.

Prescribing is free text today — a doctor types "Cefim 400mg" into a plain
input — so anything that needs to know what was actually prescribed has to
resolve that string back to a catalogue row.

This exists so allergy checking can see the ACTIVE SUBSTANCE. Once prescribing
stores a medicine_id (the next step), this becomes a fallback for historical
rows rather than the primary path.

Matching is by normalised name, deliberately narrow: exact name, name with
strength, or a registered alias. It does NOT guess. A wrong resolution here
would attach the wrong substance to a prescription and could either invent an
allergy warning or, worse, suppress a real one, so anything short of a
confident match returns nothing and the caller falls back to the typed string.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generic import Generic
from app.models.medicine import Medicine
from app.models.medicine_alias import MedicineAlias
from app.services.medicine_matcher_service import normalize


def _key(text: str | None) -> str:
    return " ".join(normalize(text or ""))


async def resolve_generic_names(
    db: AsyncSession,
    medicine_names: list[str],
) -> dict[str, str]:
    """Map each typed name to its active substance, where one is known.

    Names that match nothing are simply absent from the result — the caller
    treats that as "no extra information", not as "no allergy".
    """
    wanted = {name: _key(name) for name in medicine_names if name and name.strip()}

    if not wanted:
        return {}

    # Load the catalogue once and match in Python, because the comparison is on
    # the normalised form and the column is not normalised in the database.
    # Fine at a few hundred rows; past a few thousand this wants a stored
    # normalized_name column on medicines, as generics already has.
    rows = (
        await db.execute(
            select(
                Medicine.name,
                Medicine.strength,
                Generic.name,
            ).join(Generic, Medicine.generic_id == Generic.id, isouter=False)
        )
    ).all()

    by_key: dict[str, str] = {}

    for medicine_name, strength, generic_name in rows:
        by_key.setdefault(_key(medicine_name), generic_name)

        if strength:
            # "Cefim 400mg" is what a prescriber actually types.
            by_key.setdefault(_key(f"{medicine_name} {strength}"), generic_name)

    alias_rows = (
        await db.execute(
            select(MedicineAlias.alias, Generic.name)
            .join(Medicine, MedicineAlias.medicine_id == Medicine.id)
            .join(Generic, Medicine.generic_id == Generic.id)
        )
    ).all()

    for alias, generic_name in alias_rows:
        by_key.setdefault(_key(alias), generic_name)

    return {
        original: by_key[key]
        for original, key in wanted.items()
        if key in by_key
    }

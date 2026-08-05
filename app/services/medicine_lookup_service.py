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
from app.try_except.exceptions import BadRequestError


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


async def verify_medicine_ids(db: AsyncSession, items) -> None:
    """Reject an item naming a catalogue entry that does not exist.

    Rejecting rather than quietly nulling the link: an id that resolves to
    nothing means the client and the catalogue disagree, and the allergy check
    would then silently fall back to string matching on a request that asked
    for something stronger. Fail where a prescriber can see it.
    """
    ids = {
        item.medicine_id for item in items if getattr(item, "medicine_id", None)
    }

    if not ids:
        return

    found = set(
        (await db.scalars(select(Medicine.id).where(Medicine.id.in_(ids)))).all()
    )

    missing = sorted(ids - found)

    if missing:
        raise BadRequestError(
            "Unknown medicine selected: "
            + ", ".join(str(mid) for mid in missing)
            + ". Pick it again from the list."
        )


async def resolve_medicine_ids(
    db: AsyncSession,
    medicine_ids: list[int],
) -> dict[int, str]:
    """Map catalogue ids to their active substance.

    An id the prescriber selected is authoritative — no normalising, no
    guessing. Ids with no generic linked are absent from the result.
    """
    ids = {mid for mid in medicine_ids if mid}

    if not ids:
        return {}

    rows = (
        await db.execute(
            select(Medicine.id, Generic.name)
            .join(Generic, Medicine.generic_id == Generic.id)
            .where(Medicine.id.in_(ids))
        )
    ).all()

    return {medicine_id: generic_name for medicine_id, generic_name in rows}


async def resolve_generics_for_items(db: AsyncSession, items) -> dict[str, str]:
    """Map each item's typed name to its active substance.

    `items` is anything with `.medicine_name` and an optional `.medicine_id`.

    A selected id wins over matching the typed string: the prescriber told us
    which catalogue row they meant, so there is nothing to infer. Items without
    an id fall back to name matching, which is how every row written before
    autocomplete existed still gets checked.

    Keyed by typed name because that is what the allergy check iterates over.
    Two items sharing a name but pointing at different catalogue rows would
    collapse to one entry — pathological, and both would resolve to the same
    substance in any real catalogue.
    """
    by_id = await resolve_medicine_ids(
        db, [getattr(item, "medicine_id", None) for item in items]
    )

    unresolved = [
        item.medicine_name
        for item in items
        if getattr(item, "medicine_id", None) not in by_id
    ]

    resolved = await resolve_generic_names(db, unresolved)

    # Id matches applied last so they override anything the name lookup guessed.
    for item in items:
        generic = by_id.get(getattr(item, "medicine_id", None))
        if generic:
            resolved[item.medicine_name] = generic

    return resolved

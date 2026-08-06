"""Resolving a substance name to the Generic row that represents it.

The catalogue carries the substance twice: `medicines.generic_name` as free
text, and `medicines.generic_id` as the relation the allergy check actually
reads. The migration derived one from the other once, and nothing kept them
together afterwards — a medicine created through the admin API got no
generic_id at all, and editing generic_name changed the displayed substance
while the link kept pointing at the old one.

So every write goes through here. The string stays the display value; the
relation is derived from it, in one place, so the two cannot disagree.

Matching is on the normalised form, the same rule the backfill used: a generic
typed as "Amoxicillin + Clavulanic Acid" and one typed "amoxicillin clavulanic
acid" are the same substance, and creating a second row for the second spelling
would split a brand family and quietly halve the allergy check's reach.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generic import Generic
from app.services.medicine_matcher_service import normalize


def normalize_generic_name(name: str) -> str:
    """The comparison key for a substance name."""
    return " ".join(normalize(name or ""))


async def resolve_or_create_generic(
    db: AsyncSession,
    generic_name: str | None,
) -> Generic | None:
    """The Generic for `generic_name`, creating it if the catalogue lacks one.

    Creating rather than rejecting: a clinic adding a medicine the catalogue
    has never carried should not have to register the substance separately
    first, and refusing would leave them with the old behaviour — a medicine
    with no substance link, invisible to allergy checking.

    Returns None for a blank name, which the caller stores as a null link.
    """
    normalized = normalize_generic_name(generic_name)

    if not normalized:
        return None

    existing = await db.scalar(
        select(Generic).where(Generic.normalized_name == normalized)
    )

    if existing:
        return existing

    generic = Generic(
        name=(generic_name or "").strip(),
        normalized_name=normalized,
    )

    db.add(generic)

    # Flushed so the caller has an id to assign. The surrounding request
    # transaction still decides whether any of it is kept.
    await db.flush()

    return generic

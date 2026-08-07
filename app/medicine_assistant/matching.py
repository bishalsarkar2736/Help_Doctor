"""Working out which medicine a question is about.

Wraps the existing matcher rather than replacing it. match_medicine already
handles brand names, strengths and registered aliases, with a versioned Redis
cache and the token-run matching that stops "Ace" being found inside "place" —
none of that is worth rebuilding, and v1 still depends on it unchanged.

WHAT THIS ADDS
--------------
Generics, and honesty about ambiguity.

The matcher only knows brands and aliases. Asked for "the side effects of
Cefixime" it returns nothing, because no product is NAMED Cefixime — yet that
is one of the questions this assistant is required to answer. Cefixime is the
substance behind eleven brands.

Those eleven brands hold SIX different side-effect texts: "Diarrhea",
"Nausea, diarrhea", "Nausea", "Stomach discomfort" and two more. So there is no
single answer to give, and choosing one would be picking arbitrarily among six
records while sounding certain.

A generic therefore resolves to AMBIGUOUS with its brands as candidates, unless
the catalogue holds exactly one — in which case there is nothing to disambiguate
and the answer is that product. The caller asks which was meant.
"""

from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generic import Generic
from app.models.generic_alias import GenericAlias
from app.models.medicine import Medicine
from app.services.medicine_matcher_service import match_medicine, normalize

# How many brands to name when asking which was meant. Eleven in a chat reply
# is a wall of text; the caller can say "we have N, here are a few".
MAX_CANDIDATES = 6


class MatchStatus(str, Enum):
    OK = "ok"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"


class MatchConfidence(str, Enum):
    """How the subject was identified. Not a probability.

    A score would invite hedging — "this is probably Napa" is exactly the kind
    of sentence this assistant must never produce. These say what KIND of match
    was made, which is a fact rather than an estimate.
    """

    # The question named a product, an alias, or a product plus its strength.
    EXACT = "exact"
    # The question named a substance, and the catalogue holds one product of it.
    GENERIC_SINGLE = "generic_single"
    # The question named a substance with several products.
    GENERIC_MANY = "generic_many"
    NONE = "none"


@dataclass
class MatchResult:
    status: MatchStatus
    confidence: MatchConfidence
    medicine: Medicine | None = None
    candidates: list[Medicine] = field(default_factory=list)
    # The substance, when the question named one. Lets the caller say "Cefixime
    # is made by eleven brands" rather than "your question was ambiguous".
    generic_name: str | None = None


async def _match_generic(db: AsyncSession, question: str) -> Generic | None:
    """A substance named in the question, by its own name or a registered alias.

    Compared on the normalised form, the same rule the rest of the catalogue
    uses, so "Amoxicillin + Clavulanic Acid" and "amoxicillin clavulanic acid"
    reach the same row.
    """
    tokens = normalize(question)

    if not tokens:
        return None

    # Every contiguous run of words in the question, longest first, so a
    # two-word substance is preferred over either of its words alone.
    phrases = {
        " ".join(tokens[start : start + length])
        for length in range(min(len(tokens), 6), 0, -1)
        for start in range(len(tokens) - length + 1)
    }

    direct = (
        await db.execute(
            select(Generic)
            .where(Generic.normalized_name.in_(phrases))
            .order_by(func.length(Generic.normalized_name).desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if direct is not None:
        return direct

    return (
        await db.execute(
            select(Generic)
            .join(GenericAlias, GenericAlias.generic_id == Generic.id)
            .where(GenericAlias.normalized_alias.in_(phrases))
            .order_by(func.length(GenericAlias.normalized_alias).desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def resolve_subject(db: AsyncSession, question: str) -> MatchResult:
    """The medicine a question is about, or why there isn't one.

    A named product wins over a substance: "What is Cefim?" is about that
    product even though Cefixime is mentioned nowhere the user could see. Only
    when no product matches is the question read as being about a substance.
    """
    medicine = await match_medicine(db, question)

    if medicine is not None:
        return MatchResult(
            status=MatchStatus.OK,
            confidence=MatchConfidence.EXACT,
            medicine=medicine,
        )

    generic = await _match_generic(db, question)

    if generic is None:
        return MatchResult(
            status=MatchStatus.NOT_FOUND,
            confidence=MatchConfidence.NONE,
        )

    brands = (
        await db.scalars(
            select(Medicine)
            .where(Medicine.generic_id == generic.id)
            .order_by(Medicine.name)
        )
    ).all()

    if not brands:
        # A substance with nothing to sell under it. Known, but nothing to
        # describe — the fields this assistant reads all live on the product.
        return MatchResult(
            status=MatchStatus.NOT_FOUND,
            confidence=MatchConfidence.NONE,
            generic_name=generic.name,
        )

    if len(brands) == 1:
        return MatchResult(
            status=MatchStatus.OK,
            confidence=MatchConfidence.GENERIC_SINGLE,
            medicine=brands[0],
            generic_name=generic.name,
        )

    # Several products of the same substance, and they do NOT agree: the eleven
    # Cefixime brands hold six different side-effect texts. Answering from one
    # of them would be choosing among six while sounding certain.
    return MatchResult(
        status=MatchStatus.AMBIGUOUS,
        confidence=MatchConfidence.GENERIC_MANY,
        candidates=list(brands[:MAX_CANDIDATES]),
        generic_name=generic.name,
    )

"""Finding which medicine a free-text question is about.

WHY THIS IS NOT A SUBSTRING SEARCH
----------------------------------
It used to be `if medicine_name in question_lower`, which matches anywhere in
the string, including the middle of an unrelated word. The database contains a
medicine called "Ace", so:

    "is there any medicine i can take in place of this one"
                                          ^^^

matched Ace and the assistant answered confidently about paracetamol. Eight
medicines have names of four characters or fewer (Ace, Xpa, PPI, Rabe, Fona,
Afix, Lina, Empa), so this misfires on ordinary questions.

Matching is now on WORD BOUNDARIES, achieved by normalising both sides the same
way and comparing whole tokens:

    "Napa Extra 500mg"  ->  ["napa", "extra", "500mg"]
    question            ->  ["what", "is", "napa", "extra", "for"]

and then testing every contiguous run of question tokens against the known
names. "place" tokenises to ["place"], which is not the token "ace", so the
false match cannot occur by construction rather than by a length heuristic —
a minimum-length rule would also have broken the legitimate question "what is
Ace for?".

Normalising punctuation away means "Amoxicillin + Clavulanic Acid" and
"amoxicillin clavulanic acid" match each other, which substring matching on the
raw string never did.
"""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_cache, set_cache
from app.models.medicine import Medicine
from app.models.medicine_alias import MedicineAlias

# Longest medicine name worth considering, in tokens. Bounds the number of
# lookups per question; nothing in the catalogue is close to this.
MAX_NAME_TOKENS = 6

# Bump whenever the matching ALGORITHM changes.
#
# Cached entries are answers produced by a particular version of this code. When
# the substring matcher was replaced, every entry it had written stayed valid
# for its full TTL — so questions kept resolving to the wrong medicine after the
# bug was fixed, and only a manual redis flush cleared them. Versioning the key
# makes a deploy invalidate them by construction.
MATCHER_VERSION = "v2"

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split into tokens.

    Both medicine names and questions go through this, so they are compared on
    identical terms. Digits are kept because strength is part of a name
    ("napa 500mg").
    """
    return _NON_ALNUM.sub(" ", text.lower()).split()


def _phrases(tokens: list[str], max_len: int) -> set[str]:
    """Every contiguous run of up to max_len tokens, space-joined."""
    out: set[str] = set()

    for start in range(len(tokens)):
        for length in range(1, min(max_len, len(tokens) - start) + 1):
            out.add(" ".join(tokens[start : start + length]))

    return out


async def match_medicine(
    db: AsyncSession,
    question: str,
) -> Medicine | None:

    question_lower = question.lower().strip()

    cache_key = f"medicine_match:{MATCHER_VERSION}:{question_lower}"

    cached_medicine_id = await get_cache(cache_key)

    if cached_medicine_id:

        if cached_medicine_id == "NOT_FOUND":
            return None

        result = await db.execute(
            select(Medicine).where(Medicine.id == int(cached_medicine_id))
        )

        return result.scalar_one_or_none()

    question_phrases = _phrases(normalize(question), MAX_NAME_TOKENS)

    if not question_phrases:
        await set_cache(cache_key, "NOT_FOUND", ttl=3600)
        return None

    # (token count, character length, medicine id) so the sort below prefers
    # the most specific match: "napa extra" over "napa", and "napa 500mg" over
    # either.
    matches: list[tuple[int, int, int]] = []

    def consider(candidate: str, medicine_id: int) -> None:
        tokens = normalize(candidate)

        if not tokens or len(tokens) > MAX_NAME_TOKENS:
            return

        phrase = " ".join(tokens)

        if phrase in question_phrases:
            matches.append((len(tokens), len(phrase), medicine_id))

    # Loads the whole catalogue on a cache miss. Fine at a few hundred rows;
    # past a few thousand this wants a normalised column with an index so the
    # phrases can be looked up with a single `WHERE normalized = ANY(...)`.
    medicines = (
        await db.execute(
            select(Medicine.id, Medicine.name, Medicine.strength)
        )
    ).all()

    for medicine_id, name, strength in medicines:
        consider(name, medicine_id)

        if strength:
            # "napa 500mg" is more specific than "napa" and should win when the
            # question mentions both.
            consider(f"{name} {strength}", medicine_id)

    aliases = (
        await db.execute(
            select(MedicineAlias.alias, MedicineAlias.medicine_id)
        )
    ).all()

    for alias, medicine_id in aliases:
        consider(alias, medicine_id)

    if not matches:
        await set_cache(cache_key, "NOT_FOUND", ttl=3600)
        return None

    # Most specific wins.
    matches.sort(reverse=True)
    matched_medicine_id = matches[0][2]

    await set_cache(cache_key, matched_medicine_id, ttl=3600)

    result = await db.execute(
        select(Medicine).where(Medicine.id == matched_medicine_id)
    )

    return result.scalar_one_or_none()

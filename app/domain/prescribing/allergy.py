"""Patient allergy vs. prescribed-medicine matching.

A pragmatic safety net, not a drug database. It compares the patient's
free-text allergen list against what is being prescribed — now including the
ACTIVE SUBSTANCE, not just the brand name.

WHY THE GENERIC MATTERS
-----------------------
Brands are what a prescriber types; generics are what a patient reacts to. The
catalogue holds 11 brands of Cefixime and 7 of Metformin. Comparing brand
strings alone means a patient recorded as allergic to "Cefixime" gets NO
warning when prescribed "Cefim" — the two share almost no letters, so the test
never fired. That is a silent miss on the exact case the check exists for.

WHY NOT SUBSTRINGS
------------------
It used to ask `allergy_token in medicine_name.lower()`, which matches inside
words: an allergy to "Ace" flagged "Aceclofenac", an unrelated drug. Matching
is now on whole tokens, so "ace" no longer matches "aceclofenac" while
"Paracetamol" still matches "Paracetamol + Caffeine" — the allergen has to
appear as a complete token run within the candidate.

WHAT IT STILL WILL NOT CATCH
----------------------------
Class relationships. An allergy to "Penicillin" does not flag "Amoxicillin",
because nothing here knows they are related. That needs a coded drug/allergen
dictionary, and the limitation is why the override flow records a prescriber's
reason rather than pretending this check is authoritative.
"""

import re

_SPLIT = re.compile(r"[,\n;/]+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _normalize_tokens(text: str | None) -> list[str]:
    """Lowercase, strip punctuation, split into tokens."""
    if not text:
        return []
    return _NON_ALNUM.sub(" ", text.lower()).split()


def _allergens(allergies: str | None) -> list[list[str]]:
    """Recorded allergens, one token list per delimiter-separated entry."""
    if not allergies:
        return []

    out = []
    for raw in _SPLIT.split(allergies):
        tokens = _normalize_tokens(raw)
        if tokens:
            out.append(tokens)
    return out


def _mentions(allergen_tokens: list[str], candidate: str | None) -> bool:
    """Does the allergen appear as a whole token run inside `candidate`?"""
    tokens = _normalize_tokens(candidate)
    span = len(allergen_tokens)

    if not tokens or not span:
        return False

    return any(
        tokens[start : start + span] == allergen_tokens
        for start in range(len(tokens) - span + 1)
    )


def find_allergy_conflicts(
    allergies: str | None,
    medicine_names: list[str],
    generic_names: dict[str, str] | None = None,
) -> list[str]:
    """Return the prescribed medicines that match a recorded allergen.

    `generic_names` maps a prescribed name to its active substance, so a brand
    is also checked on what it contains. Optional and defaulting to empty: the
    caller resolves it from the catalogue where it can, and a medicine typed
    free-hand that matches no catalogue row is still checked on its name alone
    rather than skipped.
    """
    allergens = _allergens(allergies)
    if not allergens:
        return []

    generic_names = generic_names or {}

    conflicts = []

    for name in medicine_names:
        if not name:
            continue

        # What was typed, plus the substance it contains.
        candidates = [name, generic_names.get(name)]

        if any(
            _mentions(allergen, candidate)
            for allergen in allergens
            for candidate in candidates
            if candidate
        ):
            conflicts.append(name)

    return conflicts

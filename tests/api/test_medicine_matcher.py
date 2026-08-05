"""Matching a free-text question to a medicine.

The load-bearing tests are the negative ones. The previous implementation did
`if medicine_name in question_lower`, so a three-letter medicine called "Ace"
matched the word "place" and the assistant answered confidently about
paracetamol. A test that only checked "asking about Napa finds Napa" would have
passed against that too.
"""

import pytest

from app.models.medicine import Medicine
from app.models.medicine_alias import MedicineAlias
from app.services.medicine_matcher_service import (
    match_medicine,
    normalize,
)


@pytest.fixture
async def catalogue(db):
    """A slice of the real catalogue, including the short names that broke."""
    def med(name, generic, strength=None):
        # manufacturer and is_brand are NOT NULL on this table.
        return Medicine(
            name=name,
            generic_name=generic,
            strength=strength,
            manufacturer="Test Pharma",
            is_brand=True,
        )

    rows = [
        med("Ace", "Paracetamol", "500mg"),
        med("Napa", "Paracetamol", "500mg"),
        med("Napa Extra", "Paracetamol + Caffeine"),
        med("Moxaclav", "Amoxicillin + Clavulanic Acid", "625mg"),
    ]
    db.add_all(rows)
    await db.commit()
    for r in rows:
        await db.refresh(r)
    return {r.name: r.id for r in rows}


# ---------------------------------------------------------------------------
# The bug
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "is there any medicine i can take in place of this one",
        "what should i replace it with",
        "can you trace the side effects",
        "my face is swollen",
    ],
)
async def test_short_name_does_not_match_inside_a_word(db, catalogue, question):
    """'Ace' must not match 'place', 'replace', 'trace' or 'face'."""
    assert await match_medicine(db, question) is None


@pytest.mark.asyncio
async def test_the_short_name_still_matches_when_actually_mentioned(
    db, catalogue
):
    """The paired allow-case: the fix must not be a length blocklist.

    A minimum-length rule would have killed this legitimate question.
    """
    medicine = await match_medicine(db, "what is Ace for?")

    assert medicine is not None
    assert medicine.name == "Ace"


# ---------------------------------------------------------------------------
# Ordinary matching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matches_a_plain_mention(db, catalogue):
    medicine = await match_medicine(db, "what is napa used for")
    assert medicine.name == "Napa"


@pytest.mark.asyncio
async def test_prefers_the_more_specific_name(db, catalogue):
    """'Napa Extra' contains 'Napa'; the longer name must win."""
    medicine = await match_medicine(db, "tell me about napa extra")
    assert medicine.name == "Napa Extra"


@pytest.mark.asyncio
async def test_matches_name_with_strength(db, catalogue):
    medicine = await match_medicine(db, "is napa 500mg safe with food")
    assert medicine.name == "Napa"


@pytest.mark.asyncio
async def test_punctuation_is_ignored_on_both_sides(db, catalogue):
    """Substring matching on the raw string never handled this."""
    medicine = await match_medicine(db, "what about Moxaclav, is it strong?")
    assert medicine.name == "Moxaclav"


@pytest.mark.asyncio
async def test_unknown_medicine_returns_none(db, catalogue):
    assert await match_medicine(db, "what is zzzznotamedicine for") is None


@pytest.mark.asyncio
async def test_empty_question_returns_none(db, catalogue):
    assert await match_medicine(db, "   ") is None


@pytest.mark.asyncio
async def test_alias_matches(db, catalogue):
    alias = MedicineAlias(alias="Paracetamol Tablet", medicine_id=catalogue["Napa"])
    db.add(alias)
    await db.commit()

    medicine = await match_medicine(db, "what is a paracetamol tablet for")
    assert medicine.name == "Napa"


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Napa Extra", ["napa", "extra"]),
        ("Amoxicillin + Clavulanic Acid", ["amoxicillin", "clavulanic", "acid"]),
        ("NAPA-500mg", ["napa", "500mg"]),
        ("  spaced   out  ", ["spaced", "out"]),
        ("", []),
    ],
)
def test_normalize(text, expected):
    assert normalize(text) == expected

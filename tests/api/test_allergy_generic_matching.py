"""Allergy checking through the active substance.

The case that matters: a patient recorded as allergic to "Cefixime" prescribed
"Cefim". Those strings share almost nothing, so brand-name comparison never
fired — a silent miss on the exact scenario the check exists for, with eleven
Cefixime brands in the catalogue.

The unit tests below pin the matching rule; the integration test proves the
resolution actually happens on the prescribing path.
"""

import pytest
from sqlalchemy import select

from app.domain.prescribing.allergy import find_allergy_conflicts
from app.models.generic import Generic
from app.models.medicine import Medicine
from app.models.medicine_alias import MedicineAlias
from app.services.medicine_lookup_service import resolve_generic_names


# ---------------------------------------------------------------------------
# The matching rule
# ---------------------------------------------------------------------------


def test_brand_is_flagged_by_its_generic():
    """The silent miss this whole change exists to fix."""
    conflicts = find_allergy_conflicts(
        "Cefixime",
        ["Cefim 400mg"],
        {"Cefim 400mg": "Cefixime"},
    )
    assert conflicts == ["Cefim 400mg"]


def test_sibling_brands_of_the_same_generic_are_flagged():
    """Allergy recorded against one brand, prescribed another of the same drug."""
    conflicts = find_allergy_conflicts(
        "Paracetamol",
        ["Napa", "Ace"],
        {"Napa": "Paracetamol", "Ace": "Paracetamol"},
    )
    assert conflicts == ["Napa", "Ace"]


def test_allergen_matches_a_combination_generic():
    """'Paracetamol' must still flag 'Paracetamol + Caffeine'."""
    conflicts = find_allergy_conflicts(
        "Paracetamol",
        ["Napa Extra"],
        {"Napa Extra": "Paracetamol + Caffeine"},
    )
    assert conflicts == ["Napa Extra"]


def test_direct_brand_match_still_works():
    conflicts = find_allergy_conflicts("Aspirin", ["Aspirin 75mg"], {})
    assert conflicts == ["Aspirin 75mg"]


def test_does_not_match_inside_a_word():
    """'Ace' must not flag 'Aceclofenac' — a different drug entirely."""
    assert find_allergy_conflicts("Ace", ["Aceclofenac 100mg"], {}) == []


def test_unrelated_medicine_is_not_flagged():
    conflicts = find_allergy_conflicts(
        "Penicillin", ["Metformin"], {"Metformin": "Metformin"}
    )
    assert conflicts == []


def test_class_relationships_are_still_not_caught():
    """Documented limitation, asserted so it is a decision and not a surprise.

    An allergy to Penicillin does not flag Amoxicillin. Catching that needs a
    coded drug dictionary; the override flow records a prescriber's reason
    precisely because this check is not authoritative.
    """
    conflicts = find_allergy_conflicts(
        "Penicillin",
        ["Moxaclav"],
        {"Moxaclav": "Amoxicillin + Clavulanic Acid"},
    )
    assert conflicts == []


def test_multiple_allergens_are_split():
    conflicts = find_allergy_conflicts(
        "Cefixime, Metformin",
        ["Cefim", "Comet"],
        {"Cefim": "Cefixime", "Comet": "Metformin"},
    )
    assert conflicts == ["Cefim", "Comet"]


def test_no_allergies_means_no_conflicts():
    assert find_allergy_conflicts(None, ["Cefim"], {"Cefim": "Cefixime"}) == []
    assert find_allergy_conflicts("", ["Cefim"], {"Cefim": "Cefixime"}) == []


def test_unresolved_medicine_still_checked_on_its_name():
    """A free-text medicine matching no catalogue row must not be skipped."""
    conflicts = find_allergy_conflicts("Cefixime", ["Cefixime Syrup"], {})
    assert conflicts == ["Cefixime Syrup"]


# ---------------------------------------------------------------------------
# Resolution against the catalogue
# ---------------------------------------------------------------------------


@pytest.fixture
async def catalogue(db):
    cefixime = Generic(name="Cefixime", normalized_name="cefixime")
    paracetamol = Generic(name="Paracetamol", normalized_name="paracetamol")
    db.add_all([cefixime, paracetamol])
    await db.flush()

    db.add_all(
        [
            Medicine(
                name="Cefim",
                generic_name="Cefixime",
                generic_id=cefixime.id,
                strength="400mg",
                manufacturer="Test Pharma",
                is_brand=True,
            ),
            Medicine(
                name="Napa",
                generic_name="Paracetamol",
                generic_id=paracetamol.id,
                strength="500mg",
                manufacturer="Test Pharma",
                is_brand=True,
            ),
        ]
    )
    await db.commit()


@pytest.mark.asyncio
async def test_resolves_a_typed_brand_to_its_generic(db, catalogue):
    resolved = await resolve_generic_names(db, ["Cefim"])
    assert resolved == {"Cefim": "Cefixime"}


@pytest.mark.asyncio
async def test_resolves_a_brand_typed_with_its_strength(db, catalogue):
    """'Cefim 400mg' is what a prescriber actually types."""
    resolved = await resolve_generic_names(db, ["Cefim 400mg"])
    assert resolved == {"Cefim 400mg": "Cefixime"}


@pytest.mark.asyncio
async def test_unknown_name_resolves_to_nothing(db, catalogue):
    """Absent, not guessed. A wrong substance could suppress a real warning."""
    assert await resolve_generic_names(db, ["Nonexistent Drug"]) == {}


@pytest.mark.asyncio
async def test_resolution_is_case_and_punctuation_insensitive(db, catalogue):
    resolved = await resolve_generic_names(db, ["  CEFIM  "])
    assert resolved == {"  CEFIM  ": "Cefixime"}


@pytest.mark.asyncio
async def test_a_registered_alias_resolves_to_the_generic(db, catalogue):
    """medicine_aliases is empty today, so nothing else would exercise this.

    The path has to work before it is worth populating: an alias is how a
    misspelling or a local trade name reaches the right substance.
    """
    medicine = await db.scalar(select(Medicine).where(Medicine.name == "Cefim"))
    db.add(MedicineAlias(medicine_id=medicine.id, alias="Cefim-A"))
    await db.commit()

    assert await resolve_generic_names(db, ["Cefim-A"]) == {"Cefim-A": "Cefixime"}


@pytest.mark.asyncio
async def test_an_alias_makes_a_brand_inherit_the_allergy_warning(db, catalogue):
    """The alias path end to end: typed alias -> generic -> conflict."""
    medicine = await db.scalar(select(Medicine).where(Medicine.name == "Cefim"))
    db.add(MedicineAlias(medicine_id=medicine.id, alias="Cefim-A"))
    await db.commit()

    resolved = await resolve_generic_names(db, ["Cefim-A"])

    assert find_allergy_conflicts("Cefixime", ["Cefim-A"], resolved) == ["Cefim-A"]


# A test asserting that no catalogue medicine is left unlinked used to sit here.
# The test database is created empty, so it skipped on every run and never once
# executed — coverage in name only. That invariant is now enforced where it can
# actually be exercised: the generics migration fails rather than leaving a row
# unlinked, medicine create/update resolve the substance on write, and the
# seeder links from generic_id IS NULL. See test_medicine_generic_linking.py.

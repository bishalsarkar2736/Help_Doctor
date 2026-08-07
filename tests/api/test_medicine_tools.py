"""The only things the medicine assistant can ask the database.

Three properties matter beyond the happy paths.

Nothing is guessed. The eleven Cefixime brands in the catalogue hold SIX
different side-effect texts, so "the side effects of Cefixime" has no single
answer and the tools must say so rather than pick one.

field_missing is not not_found. "We have Napa but no storage guidance" and "we
have no Napa" are different facts, and blurring them would tell someone their
medicine does not exist because one column is empty.

Nothing is invented. Every value is a column, and the payload is an explicit
projection — so a field added later for an unrelated reason cannot start
appearing in public answers.
"""

import pytest
from sqlalchemy import select

from app.medicine_assistant.matching import (
    MatchConfidence,
    MatchStatus,
    resolve_subject,
)
from app.medicine_assistant.router import MedicineIntent
from app.medicine_assistant.tools import (
    SCHEMA_VERSION,
    brands_of_generic,
    medicine_detail,
    medicine_field,
)
from app.models.generic import Generic
from app.models.generic_alias import GenericAlias
from app.models.medicine import Medicine
from app.models.medicine_alias import MedicineAlias


@pytest.fixture
async def catalogue(db):
    """Two substances: one with several brands, one with a single brand."""
    cefixime = Generic(name="Cefixime", normalized_name="cefixime")
    ibuprofen = Generic(name="Ibuprofen", normalized_name="ibuprofen")
    db.add_all([cefixime, ibuprofen])
    await db.flush()

    cefim = Medicine(
        name="Cefim",
        generic_name="Cefixime",
        generic_id=cefixime.id,
        strength="400mg",
        manufacturer="Square",
        dosage_form="Tablet",
        category="Antibiotic",
        common_use="Bacterial infections",
        # Deliberately different from Ximebac's: the brands of one substance do
        # not agree in the real catalogue either.
        common_side_effects="Diarrhea",
        storage_guidance="Store below 30C",
        is_brand=True,
    )
    ximebac = Medicine(
        name="Ximebac",
        generic_name="Cefixime",
        generic_id=cefixime.id,
        strength="200mg",
        manufacturer="Beximco",
        dosage_form="Capsule",
        common_use="Bacterial infections",
        common_side_effects="Nausea, diarrhea",
        is_brand=True,
    )
    brufen = Medicine(
        name="Brufen",
        generic_name="Ibuprofen",
        generic_id=ibuprofen.id,
        strength="400mg",
        manufacturer="Square",
        dosage_form="Tablet",
        common_use="Pain and inflammation",
        # storage_guidance deliberately absent.
        is_brand=True,
    )
    db.add_all([cefim, ximebac, brufen])
    await db.flush()

    db.add(MedicineAlias(medicine_id=cefim.id, alias="Cefim-A"))
    db.add(
        GenericAlias(
            generic_id=ibuprofen.id,
            alias="Isobutylphenylpropanoic acid",
            normalized_alias="isobutylphenylpropanoic acid",
        )
    )
    await db.commit()
    return {"cefim": cefim, "ximebac": ximebac, "brufen": brufen}


# ---------------------------------------------------------------------------
# Resolving the subject
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_brand_resolves_exactly(db, catalogue):
    match = await resolve_subject(db, "What is Cefim?")

    assert match.status is MatchStatus.OK
    assert match.confidence is MatchConfidence.EXACT
    assert match.medicine.name == "Cefim"


@pytest.mark.asyncio
async def test_a_registered_alias_resolves(db, catalogue):
    """The existing matcher already handles this; it is asserted so the wrapper
    cannot quietly stop using it."""
    match = await resolve_subject(db, "Tell me about Cefim-A")

    assert match.medicine.name == "Cefim"


@pytest.mark.asyncio
async def test_a_substance_with_several_brands_is_ambiguous(db, catalogue):
    """The case the whole design turns on.

    No product is named Cefixime, and its brands do not agree about their side
    effects. Answering from one of them would be choosing while sounding sure.
    """
    match = await resolve_subject(db, "side effects of Cefixime")

    assert match.status is MatchStatus.AMBIGUOUS
    assert match.confidence is MatchConfidence.GENERIC_MANY
    assert match.medicine is None
    assert {c.name for c in match.candidates} == {"Cefim", "Ximebac"}
    assert match.generic_name == "Cefixime"


@pytest.mark.asyncio
async def test_a_substance_with_one_brand_is_not_ambiguous(db, catalogue):
    """Nothing to disambiguate, so nothing is asked."""
    match = await resolve_subject(db, "What is Ibuprofen?")

    assert match.status is MatchStatus.OK
    assert match.confidence is MatchConfidence.GENERIC_SINGLE
    assert match.medicine.name == "Brufen"


@pytest.mark.asyncio
async def test_a_substance_alias_resolves(db, catalogue):
    match = await resolve_subject(db, "What is Isobutylphenylpropanoic acid?")

    assert match.medicine.name == "Brufen"


@pytest.mark.asyncio
async def test_a_named_product_beats_its_substance(db, catalogue):
    """"What is Cefim?" is about that product, not about Cefixime generally."""
    match = await resolve_subject(db, "What is Cefim?")

    assert match.confidence is MatchConfidence.EXACT
    assert match.medicine.name == "Cefim"


@pytest.mark.asyncio
async def test_an_unknown_name_resolves_to_nothing(db, catalogue):
    match = await resolve_subject(db, "What is Nonexistentium?")

    assert match.status is MatchStatus.NOT_FOUND
    assert match.medicine is None


# ---------------------------------------------------------------------------
# medicine_detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_returns_the_recorded_record(db, catalogue):
    result = medicine_detail(await resolve_subject(db, "What is Cefim?"))

    assert result["status"] == "ok"
    assert result["medicine"]["brand_name"] == "Cefim"
    assert result["medicine"]["generic_name"] == "Cefixime"
    assert result["common_use"] == "Bacterial infections"


@pytest.mark.asyncio
async def test_detail_exposes_only_the_agreed_fields(db, catalogue):
    """An explicit projection, so a column added later for an unrelated reason
    cannot start appearing in public answers."""
    result = medicine_detail(await resolve_subject(db, "What is Cefim?"))

    assert set(result["medicine"]) == {
        "id",
        "brand_name",
        "generic_name",
        "strength",
        "dosage_form",
        "manufacturer",
        "category",
        "is_brand",
    }


@pytest.mark.asyncio
async def test_detail_relays_ambiguity(db, catalogue):
    result = medicine_detail(await resolve_subject(db, "What is Cefixime?"))

    assert result["status"] == "ambiguous"
    assert len(result["candidates"]) == 2
    assert result["medicine"] is None


# ---------------------------------------------------------------------------
# medicine_field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "intent, column, expected",
    [
        (MedicineIntent.MANUFACTURER, "manufacturer", "Square"),
        (MedicineIntent.DOSAGE_FORM, "dosage_form", "Tablet"),
        (MedicineIntent.STRENGTH, "strength", "400mg"),
        (MedicineIntent.CATEGORY, "category", "Antibiotic"),
        (MedicineIntent.GENERIC_NAME, "generic_name", "Cefixime"),
        (MedicineIntent.SIDE_EFFECTS, "common_side_effects", "Diarrhea"),
        (MedicineIntent.STORAGE, "storage_guidance", "Store below 30C"),
    ],
)
async def test_each_intent_reads_the_column_it_names(
    db, catalogue, intent, column, expected
):
    result = medicine_field(await resolve_subject(db, "What is Cefim?"), intent)

    assert result["status"] == "ok"
    assert result["field"] == column
    assert result["value"] == expected


@pytest.mark.asyncio
async def test_a_missing_field_is_not_a_missing_medicine(db, catalogue):
    """Brufen exists; its storage guidance was never filled in.

    Reporting not_found would tell someone their medicine does not exist
    because one column is empty.
    """
    result = medicine_field(
        await resolve_subject(db, "How should I store Brufen?"),
        MedicineIntent.STORAGE,
    )

    assert result["status"] == "field_missing"
    assert result["medicine"]["brand_name"] == "Brufen"
    assert result["value"] is None


@pytest.mark.asyncio
async def test_a_false_boolean_is_an_answer_not_a_gap(db, catalogue):
    """is_brand=False means "this is a generic product", not "unknown"."""
    generic_product = Medicine(
        name="Paracetamol BP",
        generic_name="Paracetamol",
        manufacturer="Generic Co",
        is_brand=False,
    )
    db.add(generic_product)
    await db.commit()

    result = medicine_field(
        await resolve_subject(db, "Is Paracetamol BP a brand or generic?"),
        MedicineIntent.BRAND_OR_GENERIC,
    )

    assert result["status"] == "ok"
    assert result["value"] is False


@pytest.mark.asyncio
async def test_a_field_question_about_a_substance_is_ambiguous(db, catalogue):
    result = medicine_field(
        await resolve_subject(db, "side effects of Cefixime"),
        MedicineIntent.SIDE_EFFECTS,
    )

    assert result["status"] == "ambiguous"
    assert result["value"] is None
    assert len(result["candidates"]) == 2


# ---------------------------------------------------------------------------
# brands_of_generic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_brands_of_a_named_substance(db, catalogue):
    match = await resolve_subject(db, "What brands contain Cefixime?")

    result = await brands_of_generic(db, match, "cefixime")

    assert result["status"] == "ok"
    assert {c["brand_name"] for c in result["candidates"]} == {"Cefim", "Ximebac"}
    assert result["brand_count"] == 2


@pytest.mark.asyncio
async def test_brands_can_be_reached_from_a_brand(db, catalogue):
    """"What else contains the same thing as Cefim?" works from either end."""
    match = await resolve_subject(db, "What brands are like Cefim?")

    result = await brands_of_generic(db, match, None)

    assert result["status"] == "ok"
    assert result["generic_name"] == "Cefixime"


@pytest.mark.asyncio
async def test_brands_of_an_unknown_substance(db, catalogue):
    match = await resolve_subject(db, "What brands contain Nonexistentium?")

    result = await brands_of_generic(db, match, "nonexistentium")

    assert result["status"] == "not_found"
    assert result["candidates"] == []


# ---------------------------------------------------------------------------
# The contract every tool honours
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_tool_returns_the_agreed_envelope(db, catalogue):
    match = await resolve_subject(db, "What is Cefim?")

    results = [
        medicine_detail(match),
        medicine_field(match, MedicineIntent.MANUFACTURER),
        await brands_of_generic(db, match, None),
    ]

    required = {
        "schema_version",
        "tool",
        "status",
        "medicine",
        "field",
        "value",
        "candidates",
        "confidence",
        "disclaimer_required",
    }

    for result in results:
        assert required <= set(result)
        assert result["schema_version"] == SCHEMA_VERSION
        assert result["status"] in {
            "ok",
            "not_found",
            "ambiguous",
            "field_missing",
        }


@pytest.mark.asyncio
async def test_a_disclaimer_is_required_whenever_information_is_returned(
    db, catalogue
):
    answered = medicine_field(
        await resolve_subject(db, "What is Cefim?"), MedicineIntent.MANUFACTURER
    )
    missing = await resolve_subject(db, "What is Nonexistentium?")

    assert answered["disclaimer_required"] is True
    assert medicine_detail(missing)["disclaimer_required"] is False


@pytest.mark.asyncio
async def test_no_tool_returns_prose(db, catalogue):
    """A tool that returned a sentence would be deciding how something is said,
    which is the one job the model has."""
    result = medicine_detail(await resolve_subject(db, "What is Cefim?"))

    for key in ("message", "text", "answer", "reply", "summary"):
        assert key not in result


@pytest.mark.asyncio
async def test_no_tool_can_produce_advice_fields(db, catalogue):
    """There is no column for interactions, pregnancy safety or dosing, so the
    assistant cannot produce them however it is asked. Structural, not a
    matter of the prompt holding."""
    result = medicine_detail(await resolve_subject(db, "What is Cefim?"))

    forbidden = {
        "interactions",
        "pregnancy",
        "contraindications",
        "dose",
        "dosage",
        "recommended_dose",
        "safety",
    }

    assert forbidden.isdisjoint(result)
    assert forbidden.isdisjoint(result["medicine"])


@pytest.mark.asyncio
async def test_the_medicine_id_is_returned_for_logging(db, catalogue):
    """What is asked ABOUT is the only thing recorded; the question is not."""
    result = medicine_detail(await resolve_subject(db, "What is Cefim?"))

    assert isinstance(result["medicine"]["id"], int)

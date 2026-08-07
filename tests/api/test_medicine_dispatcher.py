"""From a classified question to an answer, with no model involved.

The property being defended is that formatting is optional. Every fact comes
from the catalogue before a model would be consulted, so switching one off
changes how fluent the reply is and nothing about whether it is right.

Two things matter more than the individual sentences.

A refusal never reaches the database. "I'm pregnant, can I take Napa?" names a
real medicine, and a refusal that still resolved it would leave a row saying
which drug a pregnant patient asked about — the exact inference this assistant
exists to avoid, produced as a side effect of declining to answer.

And nothing invents a fact. A missing field is reported as missing; an
ambiguous substance is named rather than resolved.
"""

import pytest
from sqlalchemy import select

from app.medicine_assistant.dispatcher import dispatch
from app.medicine_assistant.responses import DISCLAIMER, build_message
from app.medicine_assistant.router import MedicineIntent, route
from app.medicine_assistant.service import answer_medicine_question_v2
from app.models.generic import Generic
from app.models.medicine import Medicine
from app.models.medicine_assistant_query import MedicineAssistantQuery


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
                manufacturer="Square",
                dosage_form="Tablet",
                category="Antibiotic",
                common_use="bacterial infections",
                common_side_effects="diarrhea",
                storage_guidance="Store below 30C",
                is_brand=True,
            ),
            Medicine(
                name="Ximebac",
                generic_name="Cefixime",
                generic_id=cefixime.id,
                strength="200mg",
                manufacturer="Beximco",
                common_side_effects="nausea",
                is_brand=True,
            ),
            Medicine(
                name="Napa",
                generic_name="Paracetamol",
                generic_id=paracetamol.id,
                strength="500mg",
                manufacturer="Beximco",
                dosage_form="Tablet",
                common_use="fever and pain",
                # storage_guidance deliberately absent
                is_brand=True,
            ),
        ]
    )
    await db.commit()


# ---------------------------------------------------------------------------
# A refusal never touches the database
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_refusal_resolves_no_medicine(db, catalogue):
    """The question names Napa. The result must not."""
    result = await dispatch(
        db, route("I'm pregnant, can I take Napa?"), "I'm pregnant, can I take Napa?"
    )

    assert result["status"] == "refused"
    assert result["medicine"] is None
    assert result["candidates"] == []


@pytest.mark.asyncio
async def test_a_refusal_makes_no_query(db, catalogue, monkeypatch):
    """Asserted by breaking the matcher: if it is called, this fails."""
    from app.medicine_assistant import matching

    async def _explode(*args, **kwargs):
        raise AssertionError("a refusal must not reach the database")

    monkeypatch.setattr(matching, "resolve_subject", _explode)

    result = await dispatch(
        db, route("Should I take this medicine?"), "Should I take this medicine?"
    )

    assert result["status"] == "refused"


@pytest.mark.asyncio
async def test_a_refused_question_logs_no_medicine(db, catalogue, default_clinic):
    """Otherwise the log records which drug a pregnant patient asked about."""
    await answer_medicine_question_v2(
        db,
        clinic_id=default_clinic.id,
        question="I'm pregnant, can I take Napa?",
    )
    await db.commit()

    row = await db.scalar(
        select(MedicineAssistantQuery).order_by(MedicineAssistantQuery.id.desc())
    )

    assert row.status == "refused"
    assert row.medicine_name is None


# ---------------------------------------------------------------------------
# Each intent reaches its tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question, tool",
    [
        ("What is Cefim?", "medicine_detail"),
        ("Who manufactures Cefim?", "medicine_field"),
        ("What brands contain Cefixime?", "brands_of_generic"),
    ],
)
async def test_intents_reach_their_tools(db, catalogue, question, tool):
    result = await dispatch(db, route(question), question)

    assert result["tool"] == tool


@pytest.mark.asyncio
async def test_an_unknown_question_reaches_no_tool(db, catalogue):
    result = await dispatch(db, route("hello"), "hello")

    assert result["status"] == "unknown"
    assert result["tool"] is None


# ---------------------------------------------------------------------------
# The sentences
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_field_answer_states_the_recorded_value(db, catalogue):
    answer = await answer_medicine_question_v2(
        db, clinic_id=1, question="Who manufactures Cefim?"
    )

    assert "Square" in answer["message"]
    assert answer["formatted_by"] == "backend"


@pytest.mark.asyncio
async def test_an_answer_carries_the_disclaimer(db, catalogue):
    answer = await answer_medicine_question_v2(
        db, clinic_id=1, question="Who manufactures Cefim?"
    )

    assert DISCLAIMER in answer["message"]


@pytest.mark.asyncio
async def test_a_refusal_carries_no_disclaimer(db, catalogue):
    """It is not medicine information, so the reference note would be noise."""
    answer = await answer_medicine_question_v2(
        db, clinic_id=1, question="Diagnose me."
    )

    assert DISCLAIMER not in answer["message"]


@pytest.mark.asyncio
async def test_each_refusal_reason_says_something_different(db, catalogue):
    """One sentence for every refusal tells a patient asking about pregnancy
    the same thing as one asking to be diagnosed."""
    messages = set()

    for question in (
        "I have diabetes, what should I use?",
        "How many tablets should I take?",
        "Can Cefim be mixed with Napa?",
        "Is Cefim safe during pregnancy?",
    ):
        answer = await answer_medicine_question_v2(
            db, clinic_id=1, question=question
        )
        messages.add(answer["message"])

    assert len(messages) == 4


@pytest.mark.asyncio
async def test_every_refusal_points_at_a_person(db, catalogue):
    """A refusal that only says no leaves someone where they started."""
    for question in (
        "Can I take Napa?",
        "How many should I take?",
        "Is this safe for children?",
    ):
        answer = await answer_medicine_question_v2(
            db, clinic_id=1, question=question
        )

        assert "doctor" in answer["message"].lower()


@pytest.mark.asyncio
async def test_a_missing_field_says_so_rather_than_denying_the_medicine(
    db, catalogue
):
    """Napa exists; its storage guidance was never recorded."""
    answer = await answer_medicine_question_v2(
        db, clinic_id=1, question="How should I store Napa?"
    )

    assert answer["result"]["status"] == "field_missing"
    assert "Napa" in answer["message"]
    assert "no storage guidance" in answer["message"].lower()


@pytest.mark.asyncio
async def test_an_ambiguous_substance_names_the_products(db, catalogue):
    answer = await answer_medicine_question_v2(
        db, clinic_id=1, question="What are the side effects of Cefixime?"
    )

    assert answer["result"]["status"] == "ambiguous"
    assert "Cefim" in answer["message"]
    assert "Ximebac" in answer["message"]


@pytest.mark.asyncio
async def test_an_unknown_medicine_is_reported_plainly(db, catalogue):
    answer = await answer_medicine_question_v2(
        db, clinic_id=1, question="What is Nonexistentium?"
    )

    assert answer["result"]["status"] == "not_found"
    assert "couldn't find" in answer["message"].lower()


@pytest.mark.asyncio
async def test_an_overview_reads_as_a_description(db, catalogue):
    answer = await answer_medicine_question_v2(
        db, clinic_id=1, question="What is Cefim?"
    )

    message = answer["message"]

    assert "Cefim" in message
    assert "Cefixime" in message
    assert "Square" in message


# ---------------------------------------------------------------------------
# What is recorded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_intent_and_outcome_are_recorded(db, catalogue, default_clinic):
    await answer_medicine_question_v2(
        db, clinic_id=default_clinic.id, question="Who manufactures Cefim?"
    )
    await db.commit()

    row = await db.scalar(
        select(MedicineAssistantQuery).order_by(MedicineAssistantQuery.id.desc())
    )

    assert row.intent == "manufacturer"
    assert row.status == "ok"
    assert row.medicine_name == "Cefim"


@pytest.mark.asyncio
async def test_the_question_is_never_recorded(db, catalogue, default_clinic):
    """Structural — the column does not exist. Asserted here too because this
    is the layer that would have written it."""
    await answer_medicine_question_v2(
        db, clinic_id=default_clinic.id, question="Who manufactures Cefim?"
    )
    await db.commit()

    row = await db.scalar(
        select(MedicineAssistantQuery).order_by(MedicineAssistantQuery.id.desc())
    )

    assert not hasattr(row, "question")


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_reply_carries_its_data(db, catalogue):
    """So a model can phrase the same payload later, and any claim can be
    checked against its source."""
    for question in ("What is Cefim?", "Diagnose me.", "hello"):
        answer = await answer_medicine_question_v2(
            db, clinic_id=1, question=question
        )

        assert answer["message"]
        assert answer["result"]["schema_version"] == 1
        assert answer["intent"]


def test_a_message_exists_for_every_status():
    """A status with no sentence would surface as an empty reply."""
    for status in (
        "ok",
        "not_found",
        "ambiguous",
        "field_missing",
        "refused",
        "unknown",
    ):
        message = build_message(
            {
                "status": status,
                "tool": "medicine_field",
                "medicine": {"brand_name": "Napa"},
                "field": "manufacturer",
                "value": "Beximco",
                "candidates": [],
                "disclaimer_required": status in ("ok", "field_missing", "ambiguous"),
            },
            MedicineIntent.MANUFACTURER,
        )

        assert message

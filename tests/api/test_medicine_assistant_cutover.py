"""Switching /medicines/assistant from v1 to v2.

The endpoint URL and the response contract do not change, so no client needs
touching. A flag decides which implementation answers, and exists so the
cutover can be undone with an environment variable rather than a redeploy —
v2 changes what the assistant REFUSES, and a refusal firing too eagerly is a
support problem that wants undoing in seconds.

The assertions here are the ones the migration turns on: no answer v1 got right
is lost, every supported question still works, substances now resolve, and
every category of medical-advice question is refused without touching the
matcher, the database or a model.
"""

import pytest

from app.config import get_settings
from app.medicine_assistant.router import MedicineIntent, route
from app.medicine_assistant.service import answer_medicine_question_v2
from app.models.generic import Generic
from app.models.medicine import Medicine
from app.services.medicine_assistant_service import answer_medicine_question


@pytest.fixture
async def catalogue(db, default_clinic):
    paracetamol = Generic(name="Paracetamol", normalized_name="paracetamol")
    cefixime = Generic(name="Cefixime", normalized_name="cefixime")
    db.add_all([paracetamol, cefixime])
    await db.flush()

    db.add_all(
        [
            Medicine(
                name="Napa", generic_name="Paracetamol", generic_id=paracetamol.id,
                strength="500mg", manufacturer="Beximco", dosage_form="Tablet",
                category="Analgesic", common_use="fever and pain",
                common_side_effects="nausea", storage_guidance="Store below 30C",
                is_brand=True,
            ),
            Medicine(
                name="Ace", generic_name="Paracetamol", generic_id=paracetamol.id,
                strength="500mg", manufacturer="Square", dosage_form="Tablet",
                category="Analgesic", common_use="pain and fever",
                common_side_effects="rash", is_brand=True,
            ),
            Medicine(
                name="Cefim", generic_name="Cefixime", generic_id=cefixime.id,
                strength="400mg", manufacturer="Square", dosage_form="Capsule",
                common_side_effects="diarrhea", is_brand=True,
            ),
            Medicine(
                name="Ximebac", generic_name="Cefixime", generic_id=cefixime.id,
                strength="200mg", manufacturer="Beximco",
                common_side_effects="nausea", is_brand=True,
            ),
        ]
    )
    await db.commit()
    return default_clinic.id


async def _v2(db, clinic_id, question):
    return await answer_medicine_question_v2(
        db, clinic_id=clinic_id, question=question, client_ip="127.0.0.1"
    )


# ---------------------------------------------------------------------------
# The flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_flag_defaults_to_v1(client, catalogue, auth_patient):
    """Nothing changes until someone decides it should."""
    assert get_settings().USE_MEDICINE_ASSISTANT_V2 is False

    res = await client.post(
        "/medicines/assistant",
        json={"question": "Who manufactures Napa?", "clinic_id": catalogue},
        headers=auth_patient["headers"],
    )

    assert res.status_code == 200, res.text
    # v1 populates only `answer`.
    assert res.json()["intent"] is None


@pytest.mark.asyncio
async def test_the_flag_switches_to_v2(client, catalogue, auth_patient, monkeypatch):
    monkeypatch.setattr(get_settings(), "USE_MEDICINE_ASSISTANT_V2", True)

    res = await client.post(
        "/medicines/assistant",
        json={"question": "Who manufactures Napa?", "clinic_id": catalogue},
        headers=auth_patient["headers"],
    )

    body = res.json()

    assert res.status_code == 200, res.text
    assert body["intent"] == "manufacturer"
    assert body["status"] == "ok"


@pytest.mark.asyncio
async def test_rollback_is_a_flag_flip(client, catalogue, auth_patient, monkeypatch):
    """The reason the flag exists: back to v1 without a redeploy."""
    monkeypatch.setattr(get_settings(), "USE_MEDICINE_ASSISTANT_V2", True)

    on = await client.post(
        "/medicines/assistant",
        json={"question": "Diagnose me.", "clinic_id": catalogue},
        headers=auth_patient["headers"],
    )

    monkeypatch.setattr(get_settings(), "USE_MEDICINE_ASSISTANT_V2", False)

    off = await client.post(
        "/medicines/assistant",
        json={"question": "Diagnose me.", "clinic_id": catalogue},
        headers=auth_patient["headers"],
    )

    assert on.json()["status"] == "refused"
    assert off.json()["status"] is None


# ---------------------------------------------------------------------------
# The response contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_answer_is_always_present(client, catalogue, auth_patient, monkeypatch):
    """The field every existing client reads, under both implementations."""
    for enabled in (False, True):
        monkeypatch.setattr(get_settings(), "USE_MEDICINE_ASSISTANT_V2", enabled)

        res = await client.post(
            "/medicines/assistant",
            json={"question": "Who manufactures Napa?", "clinic_id": catalogue},
            headers=auth_patient["headers"],
        )

        assert isinstance(res.json()["answer"], str)
        assert res.json()["answer"]


@pytest.mark.asyncio
async def test_the_new_fields_are_additive(
    client, catalogue, auth_patient, monkeypatch
):
    """A client that reads only `answer` is unaffected by their presence."""
    monkeypatch.setattr(get_settings(), "USE_MEDICINE_ASSISTANT_V2", True)

    res = await client.post(
        "/medicines/assistant",
        json={"question": "Who manufactures Napa?", "clinic_id": catalogue},
        headers=auth_patient["headers"],
    )

    body = res.json()

    assert set(body) == {"answer", "intent", "status", "result"}
    assert body["result"]["schema_version"] == 1


@pytest.mark.asyncio
async def test_the_endpoint_still_requires_authentication(client, catalogue):
    """Auth, rate limiting and tenant resolution are reused, not rebuilt."""
    res = await client.post(
        "/medicines/assistant",
        json={"question": "Who manufactures Napa?", "clinic_id": catalogue},
    )

    assert res.status_code == 401, res.text


# ---------------------------------------------------------------------------
# No answer v1 got right is lost
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "What is Napa?",
        "What is the generic of Napa?",
        "What is the common use of Ace?",
        "How should I store Napa?",
        "Who manufactures Napa?",
        "What dosage form is Ace?",
        "What strength is Napa?",
        "What category is Ace?",
    ],
)
async def test_v2_answers_everything_v1_answered(db, catalogue, question):
    """The migration's core promise, checked question by question."""
    v1_answer = await answer_medicine_question(
        db=db, clinic_id=catalogue, question=question
    )
    v2 = await _v2(db, catalogue, question)

    v1_worked = "could not find" not in v1_answer.lower()

    if v1_worked:
        assert v2["result"]["status"] in ("ok", "ambiguous", "field_missing"), (
            f"v1 answered {question!r} and v2 did not"
        )


@pytest.mark.asyncio
async def test_generic_queries_now_resolve(db, catalogue):
    """v1 returns nothing for a substance; this is the headline fix."""
    v1_answer = await answer_medicine_question(
        db=db, clinic_id=catalogue, question="side effects of Cefixime"
    )
    v2 = await _v2(db, catalogue, "side effects of Cefixime")

    assert "could not find" in v1_answer.lower()
    assert v2["result"]["status"] == "ambiguous"
    assert {c["brand_name"] for c in v2["result"]["candidates"]} == {
        "Cefim",
        "Ximebac",
    }


# ---------------------------------------------------------------------------
# Every category of advice question is refused
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question, category",
    [
        ("I have HIV. Can I take Napa?", "patient context"),
        ("I'm pregnant. Can I use this medicine?", "pregnancy"),
        ("My child has fever.", "patient context"),
        ("What antibiotic should I take?", "recommendation"),
        ("Can I combine Napa and Ace?", "interaction"),
        ("Diagnose me.", "diagnosis"),
        ("How many tablets of Napa should I take?", "dosage"),
        ("Is Napa safe during pregnancy?", "pregnancy"),
        ("Recommend medicine.", "recommendation"),
        ("Should I take Ace?", "personal advice"),
    ],
)
async def test_advice_questions_are_refused(db, catalogue, question, category):
    answer = await _v2(db, catalogue, question)

    assert answer["result"]["status"] == "refused", f"{category} was not refused"
    assert answer["intent"] == MedicineIntent.REFUSE.value


@pytest.mark.asyncio
async def test_v1_answered_advice_questions_with_medicine_information(db, catalogue):
    """Why this migration matters, asserted rather than asserted about.

    Asked whether two medicines can be combined, v1 replies with a description
    of one of them. It reads as an answer to the question that was asked.
    """
    v1_answer = await answer_medicine_question(
        db=db, clinic_id=catalogue, question="Can I combine Napa and Ace?"
    )

    assert "Napa" in v1_answer
    assert "could not find" not in v1_answer.lower()

    v2 = await _v2(db, catalogue, "Can I combine Napa and Ace?")

    assert v2["result"]["status"] == "refused"


# ---------------------------------------------------------------------------
# A refusal touches nothing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_refusal_reaches_neither_matcher_nor_model(
    db, catalogue, monkeypatch
):
    """Asserted by breaking both: if either is called, this fails."""
    from app.medicine_assistant import llm, matching

    async def _no_matcher(*args, **kwargs):
        raise AssertionError("a refusal must not reach the matcher")

    async def _no_model(*args, **kwargs):
        raise AssertionError("a refusal must not reach the model")

    monkeypatch.setattr(matching, "resolve_subject", _no_matcher)
    monkeypatch.setattr(llm, "format_answer", _no_model)
    monkeypatch.setattr(get_settings(), "ENABLE_MEDICINE_AI_FORMATTING", True)
    monkeypatch.setattr(get_settings(), "OPENAI_API_KEY", "test-key")

    answer = await _v2(db, catalogue, "I'm pregnant, can I take Napa?")

    assert answer["result"]["status"] == "refused"


@pytest.mark.asyncio
async def test_a_refusal_records_no_medicine(db, catalogue):
    """Even though the question named one."""
    from sqlalchemy import select

    from app.models.medicine_assistant_query import MedicineAssistantQuery

    await _v2(db, catalogue, "I'm pregnant, can I take Napa?")
    await db.commit()

    row = await db.scalar(
        select(MedicineAssistantQuery).order_by(MedicineAssistantQuery.id.desc())
    )

    assert row.status == "refused"
    assert row.medicine_name is None


# ---------------------------------------------------------------------------
# Nothing a patient typed is stored, under either implementation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_neither_implementation_can_store_a_question(db, catalogue):
    """Structural: the columns do not exist."""
    from sqlalchemy import inspect

    from app.models.medicine_ai_log import MedicineAILog
    from app.models.medicine_assistant_query import MedicineAssistantQuery

    for model in (MedicineAssistantQuery, MedicineAILog):
        columns = {c.key for c in inspect(model).columns}

        assert "question" not in columns
        assert "answer" not in columns


# ---------------------------------------------------------------------------
# The router still separates the two populations of question
# ---------------------------------------------------------------------------


def test_every_supported_question_routes_to_an_answerable_intent():
    """A guard on the migration report's premise."""
    for question in (
        "What is Napa Extra?",
        "Tell me about Cef-3.",
        "What is the generic of Napa?",
        "What is the common use of Ace?",
        "What are the common side effects of Cefixime?",
        "How should I store Napa?",
        "Who manufactures Napa?",
        "What dosage form is Ace?",
    ):
        assert route(question).is_known, question

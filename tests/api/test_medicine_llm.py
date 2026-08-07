"""The model's place in the medicine assistant, and the limits around it.

The property being defended is that formatting is optional. Every fact comes
from the catalogue before a model is consulted, so switching it off, running
out of budget, or having OpenAI fall over all degrade the WORDING and never the
answer.

Two limits are stricter here than in the scheduling assistant.

The model never routes. There is no classification fallback: an unrecognised
question gets the deterministic reply rather than a model's opinion about what
it might have meant.

And a refusal never reaches the model at all. Asking one to phrase a refusal is
asking it to negotiate one, which is precisely what a patient trying to get
advice out of it would be probing for.

Nothing here calls OpenAI — the client is replaced, and one test asserts the
deterministic path never reaches for it.
"""

import pytest

from app.config import get_settings
from app.medicine_assistant import llm, service
from app.models.generic import Generic
from app.models.medicine import Medicine
from app.models.medicine_ai_log import MedicineAILog


@pytest.fixture
async def catalogue(db, default_clinic):
    """Returns the clinic id: medicine_ai_logs has an FK to clinics, so the
    cost rows these tests assert on need a real one."""
    generic = Generic(name="Paracetamol", normalized_name="paracetamol")
    db.add(generic)
    await db.flush()

    db.add(
        Medicine(
            name="Napa",
            generic_name="Paracetamol",
            generic_id=generic.id,
            strength="500mg",
            manufacturer="Beximco",
            dosage_form="Tablet",
            common_use="fever and pain",
            common_side_effects="nausea",
            storage_guidance="Store below 30C",
            is_brand=True,
        )
    )
    await db.commit()
    return default_clinic.id


@pytest.fixture
def ai_on(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ENABLE_MEDICINE_AI_FORMATTING", True)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    return settings


@pytest.fixture
def fake_llm(monkeypatch):
    """Record calls instead of making them."""
    calls = []

    async def _format(question, result):
        calls.append({"question": question, "result": result})
        return "Napa is made by Beximco.", 42, 12

    monkeypatch.setattr(llm, "format_answer", _format)
    return calls


async def _ask(db, clinic_id, question, **kwargs):
    return await service.answer_medicine_question_v2(
        db, clinic_id=clinic_id, question=question, client_ip="1.1.1.1", **kwargs
    )


# ---------------------------------------------------------------------------
# The deterministic path spends nothing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_model_is_not_called_when_disabled(db, catalogue, monkeypatch):
    called = False

    async def _explode(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("the model must not be called")

    monkeypatch.setattr(llm, "format_answer", _explode)
    monkeypatch.setattr(get_settings(), "ENABLE_MEDICINE_AI_FORMATTING", False)

    answer = await _ask(db, catalogue, "Who manufactures Napa?")

    assert called is False
    assert answer["formatted_by"] == "backend"
    assert "Beximco" in answer["message"]


@pytest.mark.asyncio
async def test_a_missing_api_key_disables_it(monkeypatch):
    """Misconfiguration degrades exactly like the switch being off."""
    settings = get_settings()
    monkeypatch.setattr(settings, "ENABLE_MEDICINE_AI_FORMATTING", True)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)

    assert llm.is_enabled() is False


# ---------------------------------------------------------------------------
# A refusal never reaches the model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_refusal_is_never_sent_to_the_model(
    db, catalogue, ai_on, fake_llm
):
    """Asking a model to phrase a refusal is asking it to negotiate one."""
    answer = await _ask(db, catalogue, "I'm pregnant, can I take Napa?")

    assert fake_llm == []
    assert answer["formatted_by"] == "backend"
    assert answer["result"]["status"] == "refused"


@pytest.mark.asyncio
async def test_an_unknown_question_is_never_sent_to_the_model(
    db, catalogue, ai_on, fake_llm
):
    """No classification fallback: the router is deterministic and stays so."""
    answer = await _ask(db, catalogue, "hello")

    assert fake_llm == []
    assert answer["intent"] == "unknown"


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_answerable_question_is_formatted(db, catalogue, ai_on, fake_llm):
    answer = await _ask(db, catalogue, "Who manufactures Napa?")

    assert len(fake_llm) == 1
    assert answer["formatted_by"] == "llm"
    assert answer["message"] == "Napa is made by Beximco."


@pytest.mark.asyncio
async def test_the_model_never_replaces_the_data(db, catalogue, ai_on, fake_llm):
    """Its sentence is returned alongside the payload, never instead of it."""
    answer = await _ask(db, catalogue, "Who manufactures Napa?")

    assert answer["result"]["value"] == "Beximco"
    assert answer["result"]["medicine"]["brand_name"] == "Napa"


@pytest.mark.asyncio
async def test_the_model_receives_the_result_not_a_query(
    db, catalogue, ai_on, fake_llm
):
    """It is handed an answer, never the means to compute one."""
    await _ask(db, catalogue, "Who manufactures Napa?")

    payload = fake_llm[0]["result"]

    assert payload["status"] == "ok"
    assert payload["value"] == "Beximco"
    assert "sql" not in str(payload).lower()


@pytest.mark.asyncio
async def test_a_failure_falls_back_to_the_computed_answer(
    db, catalogue, ai_on, monkeypatch
):
    """The assistant must not fail because OpenAI did."""
    from app.integrations.openai_client import OpenAIClient

    async def _boom(self, prompt):
        raise TimeoutError("upstream timed out")

    monkeypatch.setattr(OpenAIClient, "generate", _boom)

    answer = await _ask(db, catalogue, "Who manufactures Napa?")

    assert answer["formatted_by"] == "backend"
    assert "Beximco" in answer["message"]


# ---------------------------------------------------------------------------
# The guardrail over the output
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forbidden_output_is_replaced(db, catalogue, ai_on, monkeypatch):
    """The prompt asks; the guardrail checks.

    A prompt is a request rather than a guarantee, so a reply carrying dosage
    or diagnosis language is replaced rather than shown.
    """
    from app.integrations.openai_client import OpenAIClient

    async def _advice(self, prompt):
        return "You should take 2 tablets twice a day.", 10

    monkeypatch.setattr(OpenAIClient, "generate", _advice)

    text, _, _ = await llm.format_answer("Who manufactures Napa?", {"status": "ok"})

    assert "take 2 tablets" not in text.lower()


@pytest.mark.asyncio
async def test_the_prompt_forbids_advice(db, catalogue):
    """Asserted on the instructions themselves, so a later edit that removes a
    rule fails here rather than in production."""
    prompt = llm.build_prompt("What is Napa?", {"status": "ok"})

    lowered = prompt.lower()

    for rule in ("never add a fact", "never state or suggest a dose",
                 "never diagnose", "safe or unsafe"):
        assert rule in lowered


# ---------------------------------------------------------------------------
# Spending limits, shared with the scheduling assistant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_daily_budget_stops_the_model(
    db, catalogue, ai_on, monkeypatch, fake_llm
):
    monkeypatch.setattr(get_settings(), "MAX_LLM_REQUESTS_PER_CLINIC_PER_DAY", 0)

    answer = await _ask(db, catalogue, "Who manufactures Napa?")

    assert fake_llm == []
    assert answer["llm_unavailable_reason"] == "daily_budget_exceeded"


@pytest.mark.asyncio
async def test_a_throttled_clinic_still_gets_a_real_answer(
    db, catalogue, ai_on, monkeypatch
):
    """Out of AI budget is not out of service. The catalogue costs nothing."""
    monkeypatch.setattr(get_settings(), "MAX_LLM_REQUESTS_PER_CLINIC_PER_DAY", 0)

    answer = await _ask(db, catalogue, "Who manufactures Napa?")

    assert answer["result"]["status"] == "ok"
    assert "Beximco" in answer["message"]


@pytest.mark.asyncio
async def test_the_per_ip_limit_stops_the_model(db, catalogue, ai_on, monkeypatch):
    monkeypatch.setattr(get_settings(), "MAX_LLM_REQUESTS_PER_IP_PER_MINUTE", 1)

    calls = []

    async def _format(question, result):
        calls.append(question)
        return "Formatted.", 1, 1

    monkeypatch.setattr(llm, "format_answer", _format)

    first = await service.answer_medicine_question_v2(
        db, clinic_id=catalogue, question="Who manufactures Napa?",
        client_ip="7.7.7.7",
    )
    second = await service.answer_medicine_question_v2(
        db, clinic_id=catalogue, question="Who manufactures Napa?",
        client_ip="7.7.7.7",
    )

    assert first["formatted_by"] == "llm"
    assert second["llm_unavailable_reason"] == "rate_limited"
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# What is recorded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_is_recorded_without_the_text(db, catalogue, ai_on, fake_llm):
    from sqlalchemy import select

    await service.answer_medicine_question_v2(
        db,
        clinic_id=catalogue,
        question="Who manufactures Napa?",
        client_ip="2.2.2.2",
    )
    await db.commit()

    log = await db.scalar(select(MedicineAILog).order_by(MedicineAILog.id.desc()))

    assert log.tokens_used == 42
    assert log.medicine_name == "Napa"
    assert not hasattr(log, "question")
    assert not hasattr(log, "answer")


@pytest.mark.asyncio
async def test_nothing_is_logged_when_the_model_is_not_used(db, catalogue):
    """No model call, no cost row."""
    from sqlalchemy import select, func

    before = await db.scalar(select(func.count(MedicineAILog.id)))

    await service.answer_medicine_question_v2(
        db,
        clinic_id=catalogue,
        question="Who manufactures Napa?",
        client_ip="3.3.3.3",
    )
    await db.commit()

    assert await db.scalar(select(func.count(MedicineAILog.id))) == before

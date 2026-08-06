"""The model's place in the assistant, and the limits around it.

The property being defended is that the model is optional. Every fact comes
from the database before the model is consulted, so switching it off, running
out of budget, or having OpenAI fall over all degrade the WORDING and never the
answer.

Nothing here calls OpenAI. The client is replaced, and one test asserts the
deterministic path never reaches for it at all — that is the guarantee, and it
is worth checking rather than assuming.
"""

import pytest

from app.assistant import llm, service
from app.assistant.router import Intent
from app.config import get_settings
from app.models.clinic import Clinic, ClinicStatus
from app.models.doctor import Doctor, DoctorStatus
from app.models.user import User, UserRole


@pytest.fixture
async def clinic(db):
    clinic = Clinic(
        name="Dhaka Clinic",
        status=ClinicStatus.ACTIVE,
        timezone="Asia/Dhaka",
        phone="+8801700000000",
        opening_hours={"0": [{"open": "09:00", "close": "17:00"}]},
    )
    db.add(clinic)
    await db.flush()

    user = User(
        email="llm-doc@test.com",
        full_name="Dr Rahman",
        hashed_password="x",
        role=UserRole.DOCTOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    db.add(
        Doctor(
            user_id=user.id,
            clinic_id=clinic.id,
            specialization="Cardiology",
            experience_years=5,
            bio="Doctor",
            status=DoctorStatus.APPROVED,
        )
    )
    await db.commit()
    return clinic


@pytest.fixture
def ai_on(monkeypatch):
    """Enable the model, with a key present so is_enabled() is satisfied."""
    settings = get_settings()
    monkeypatch.setattr(settings, "ENABLE_AI_FORMATTING", True)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    return settings


@pytest.fixture
def fake_llm(monkeypatch):
    """Record calls instead of making them."""
    calls = []

    async def _call(prompt: str, *, purpose: str):
        calls.append({"purpose": purpose, "prompt": prompt})
        return "Dr Rahman is free at 2:00 PM." if purpose == "format" else "unknown"

    monkeypatch.setattr(llm, "_call", _call)
    return calls


# ---------------------------------------------------------------------------
# The deterministic path never spends a call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_model_is_not_called_when_the_feature_is_off(
    db, clinic, monkeypatch
):
    called = False

    async def _explode(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("the model must not be called")

    monkeypatch.setattr(llm, "_call", _explode)
    monkeypatch.setattr(get_settings(), "ENABLE_AI_FORMATTING", False)

    result = await service.answer(db, clinic, "When do you close?", client_ip="1.1.1.1")

    assert called is False
    assert result["formatted_by"] == "backend"


@pytest.mark.asyncio
async def test_the_answer_is_complete_without_the_model(db, clinic, monkeypatch):
    """Switching the model off changes the wording, not the facts."""
    monkeypatch.setattr(get_settings(), "ENABLE_AI_FORMATTING", False)

    result = await service.answer(
        db, clinic, "I need a cardiologist", client_ip="1.1.1.1"
    )

    assert result["result"]["tool"] == "search_doctors"
    assert result["result"]["doctors"][0]["name"] == "Dr Rahman"
    assert result["message"]


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_known_question_is_formatted_not_classified(
    db, clinic, ai_on, fake_llm
):
    """The router placed it, so the model is asked to word it and nothing more."""
    await service.answer(db, clinic, "I need a cardiologist", client_ip="1.1.1.1")

    assert [c["purpose"] for c in fake_llm] == ["format"]


@pytest.mark.asyncio
async def test_the_model_never_replaces_the_facts(db, clinic, ai_on, fake_llm):
    """Its sentence is returned alongside the data, never instead of it."""
    result = await service.answer(
        db, clinic, "I need a cardiologist", client_ip="1.1.1.1"
    )

    assert result["message"] == "Dr Rahman is free at 2:00 PM."
    assert result["formatted_by"] == "llm"
    # The structured result is untouched by whatever the model said.
    assert result["result"]["doctors"][0]["name"] == "Dr Rahman"


@pytest.mark.asyncio
async def test_the_prompt_carries_the_result_not_a_query(
    db, clinic, ai_on, fake_llm
):
    """The model is handed an answer, never the means to compute one."""
    await service.answer(db, clinic, "I need a cardiologist", client_ip="1.1.1.1")

    prompt = fake_llm[0]["prompt"]

    assert "Dr Rahman" in prompt
    assert "SELECT" not in prompt.upper()


# ---------------------------------------------------------------------------
# Classification, only for what the rules could not place
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_question_is_classified(db, clinic, ai_on, monkeypatch):
    async def _call(prompt: str, *, purpose: str):
        return "clinic_information" if purpose == "classify" else "Ok."

    monkeypatch.setattr(llm, "_call", _call)

    result = await service.answer(
        db, clinic, "hmm what about the place itself", client_ip="1.1.1.1"
    )

    assert result["intent"] == Intent.CLINIC_INFORMATION.value


@pytest.mark.asyncio
async def test_an_invented_intent_is_discarded(db, clinic, ai_on, monkeypatch):
    """A model that names a capability nobody wrote must reach no tool."""
    async def _call(prompt: str, *, purpose: str):
        return "book_appointment" if purpose == "classify" else "Ok."

    monkeypatch.setattr(llm, "_call", _call)

    result = await service.answer(db, clinic, "gibberish here", client_ip="1.1.1.1")

    assert result["intent"] == Intent.UNKNOWN.value
    assert result["result"]["status"] == "unsupported"


@pytest.mark.asyncio
async def test_classification_is_not_attempted_for_a_known_question(
    db, clinic, ai_on, fake_llm
):
    await service.answer(db, clinic, "When do you close?", client_ip="1.1.1.1")

    assert "classify" not in [c["purpose"] for c in fake_llm]


# ---------------------------------------------------------------------------
# Failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_openai_failure_falls_back(db, clinic, ai_on, monkeypatch):
    """The assistant must not fail because OpenAI did."""
    from app.integrations.openai_client import OpenAIClient

    async def _boom(self, prompt):
        raise TimeoutError("upstream timed out")

    monkeypatch.setattr(OpenAIClient, "generate", _boom)

    result = await service.answer(
        db, clinic, "I need a cardiologist", client_ip="1.1.1.1"
    )

    assert result["formatted_by"] == "backend"
    assert result["result"]["doctors"][0]["name"] == "Dr Rahman"
    assert result["message"]


@pytest.mark.asyncio
async def test_a_missing_api_key_disables_the_model(db, clinic, monkeypatch):
    """Misconfiguration degrades exactly like the switch being off."""
    settings = get_settings()
    monkeypatch.setattr(settings, "ENABLE_AI_FORMATTING", True)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)

    assert llm.is_enabled() is False


# ---------------------------------------------------------------------------
# Spending limits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_daily_budget_stops_the_model(db, clinic, ai_on, monkeypatch):
    monkeypatch.setattr(
        get_settings(), "MAX_LLM_REQUESTS_PER_CLINIC_PER_DAY", 0
    )

    called = False

    async def _explode(*args, **kwargs):
        nonlocal called
        called = True
        return "should not happen"

    monkeypatch.setattr(llm, "_call", _explode)

    result = await service.answer(
        db, clinic, "I need a cardiologist", client_ip="9.9.9.9"
    )

    assert called is False
    assert result["llm_unavailable_reason"] == "daily_budget_exceeded"
    assert result["message"] == service.BUDGET_MESSAGE


@pytest.mark.asyncio
async def test_the_per_ip_limit_stops_the_model(db, clinic, ai_on, monkeypatch):
    monkeypatch.setattr(get_settings(), "MAX_LLM_REQUESTS_PER_IP_PER_MINUTE", 1)

    calls = []

    async def _call(prompt: str, *, purpose: str):
        calls.append(purpose)
        return "Ok."

    monkeypatch.setattr(llm, "_call", _call)

    first = await service.answer(
        db, clinic, "I need a cardiologist", client_ip="7.7.7.7"
    )
    second = await service.answer(
        db, clinic, "I need a cardiologist", client_ip="7.7.7.7"
    )

    assert first["formatted_by"] == "llm"
    assert second["llm_unavailable_reason"] == "rate_limited"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_throttled_clinic_still_gets_a_real_answer(
    db, clinic, ai_on, monkeypatch
):
    """Out of AI budget is not out of service.

    The deterministic path costs nothing, so it is never throttled with the
    model — a clinic that has exhausted its ceiling can still answer questions
    from the database all day.
    """
    monkeypatch.setattr(get_settings(), "MAX_LLM_REQUESTS_PER_CLINIC_PER_DAY", 0)

    result = await service.answer(
        db, clinic, "I need a cardiologist", client_ip="8.8.8.8"
    )

    assert result["result"]["status"] == "ok"
    assert result["result"]["doctors"][0]["name"] == "Dr Rahman"


@pytest.mark.asyncio
async def test_limits_are_per_ip(db, clinic, ai_on, monkeypatch):
    monkeypatch.setattr(get_settings(), "MAX_LLM_REQUESTS_PER_IP_PER_MINUTE", 1)

    async def _call(prompt: str, *, purpose: str):
        return "Ok."

    monkeypatch.setattr(llm, "_call", _call)

    await service.answer(db, clinic, "I need a cardiologist", client_ip="3.3.3.3")
    other = await service.answer(
        db, clinic, "I need a cardiologist", client_ip="4.4.4.4"
    )

    assert other["llm_unavailable_reason"] is None


# ---------------------------------------------------------------------------
# What is never recorded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_conversation_state_is_kept(db, clinic, ai_on, fake_llm):
    """Two identical questions are two independent calls.

    No history, no memory, no cached reply — a chat box invites people to
    describe their health, and the surest way never to mishandle that text is
    never to keep it.
    """
    await service.answer(db, clinic, "I need a cardiologist", client_ip="5.5.5.5")
    await service.answer(db, clinic, "I need a cardiologist", client_ip="5.5.5.5")

    assert len(fake_llm) == 2

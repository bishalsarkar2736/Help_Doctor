"""Turning an answer the backend already computed into a sentence.

The model's whole job is wording. Every fact in the reply — which doctors,
which times, whether the clinic is open — was decided by a query before this
module is reached, and is handed over as structured data. Nothing here asks the
model what is true.

That is why a small model is the right one. There is no reasoning left to do:
the backend did it. A larger model would cost more, answer more slowly, and be
no less bound by the data it was given.

WHAT IT IS NOT ALLOWED TO DO
----------------------------
Add a doctor, a time, a phone number or an opinion. The prompt says so, but a
prompt is a request rather than a guarantee — so the caller keeps the
structured result alongside the sentence, the deterministic answer is always
available, and any failure returns that instead of an apology.

The model also never chooses a tool. Tool selection is the router's, and stays
deterministic; the model is consulted only when the router could not classify
the question at all, and then only to pick from a fixed list of intents.

NO PROMPTS ARE STORED
---------------------
Not the question, not the reply. What is recorded is that a call happened, how
long it took, whether it worked and what it cost. A patient may type anything
into a chat box, including things about their health, and the cheapest way to
never mishandle that text is to never keep it.
"""

import logging
import time

from app.assistant.router import Intent
from app.config import get_settings
from app.core.metrics import (
    assistant_llm_failures_total,
    assistant_llm_latency_seconds,
    assistant_llm_requests_total,
    assistant_llm_tokens_total,
)
from app.integrations.openai_client import OpenAIClient

logger = logging.getLogger(__name__)

# Every intent the router can produce. The classifier picks from this and
# nothing else, so a model that invents a capability produces a value the
# dispatcher rejects rather than a tool call nobody wrote.
CLASSIFIABLE = [
    Intent.DOCTOR_AVAILABILITY.value,
    Intent.EARLIEST_SLOT.value,
    Intent.LIST_SPECIALIZATIONS.value,
    Intent.SEARCH_DOCTORS.value,
    Intent.CLINIC_INFORMATION.value,
    Intent.UNKNOWN.value,
]

FORMAT_INSTRUCTIONS = """\
You write one short reply for a medical clinic's scheduling assistant.

You are given a JSON result that the clinic's own system produced. Rewrite it
as one or two plain sentences a patient would understand.

Rules:
- Use ONLY facts present in the JSON. Never add a doctor, a time, a date, a
  price, a phone number or an address that is not there.
- Never estimate, guess, or say a doctor is "probably" or "usually" available.
- If the result is empty, say plainly that nothing was found. Do not suggest
  an alternative that is not in the JSON.
- Do not give medical advice, and do not interpret symptoms. If the question
  looks medical, say the assistant only helps with appointments and clinic
  information.
- Repeat times and dates exactly as written. They are already in the clinic's
  local time; do not convert or re-word them.
- No greetings, no sign-offs, no emoji, no markdown.
"""

CLASSIFY_INSTRUCTIONS = """\
Classify a patient's question for a clinic scheduling assistant.

Reply with exactly one word from this list and nothing else:
{options}

Meanings:
- doctor_availability: when a NAMED doctor is free
- earliest_slot: the soonest appointment with anyone
- list_specializations: what kinds of doctors the clinic has
- search_doctors: finding a doctor by name or by kind
- clinic_information: address, phone, opening hours, holidays
- unknown: anything else, including medical questions and small talk
"""


def is_enabled() -> bool:
    settings = get_settings()

    # A missing key disables it as surely as the flag does. Checking both here
    # means the caller never has to distinguish "switched off" from
    # "misconfigured" — either way the deterministic answer is returned.
    return bool(settings.ENABLE_AI_FORMATTING and settings.OPENAI_API_KEY)


def _client() -> OpenAIClient:
    client = OpenAIClient()

    # The assistant's model is set separately from the medicine assistant's:
    # this one only rewrites JSON, and paying for a larger model to do it buys
    # nothing.
    client.model = get_settings().ASSISTANT_LLM_MODEL

    return client


async def _call(prompt: str, *, purpose: str) -> str | None:
    """One model call, instrumented, never raising.

    A failure here is not a failure of the assistant: the caller already holds
    a correct answer and only wanted it phrased. Timeouts, quota errors and
    outages all return None and the deterministic reply is used.
    """
    assistant_llm_requests_total.labels(purpose=purpose).inc()

    started = time.perf_counter()

    try:
        text, tokens = await _client().generate(prompt)

        assistant_llm_latency_seconds.labels(purpose=purpose).observe(
            time.perf_counter() - started
        )
        assistant_llm_tokens_total.labels(purpose=purpose).inc(tokens or 0)

        return (text or "").strip() or None

    except Exception as exc:
        assistant_llm_failures_total.labels(
            purpose=purpose, kind=type(exc).__name__
        ).inc()

        # The exception type only. The message can echo the prompt, and the
        # prompt contains whatever the patient typed.
        logger.warning(
            "assistant llm call failed", extra={"purpose": purpose,
                                                "error": type(exc).__name__}
        )
        return None


async def format_answer(question: str, result: dict) -> str | None:
    """Phrase an already-computed answer, or None to use the structured one."""
    if not is_enabled():
        return None

    import json

    prompt = (
        f"{FORMAT_INSTRUCTIONS}\n"
        f"Patient asked: {question}\n\n"
        f"Result JSON:\n{json.dumps(result, ensure_ascii=False, default=str)}\n\n"
        "Reply:"
    )

    return await _call(prompt, purpose="format")


async def classify(question: str) -> Intent | None:
    """A second opinion on a question the router could not place.

    Only ever consulted after the deterministic router has returned UNKNOWN,
    and only to choose from the fixed list above. Anything else it says is
    discarded.
    """
    if not is_enabled():
        return None

    prompt = (
        CLASSIFY_INSTRUCTIONS.format(options=", ".join(CLASSIFIABLE))
        + f"\nQuestion: {question}\nAnswer:"
    )

    answer = await _call(prompt, purpose="classify")

    if not answer:
        return None

    candidate = answer.strip().lower().split()[0].strip(".,\"'")

    if candidate not in CLASSIFIABLE:
        # An unrecognised label is treated as no answer. A model that invents
        # a capability must not be able to reach a tool through this door.
        return None

    return Intent(candidate)

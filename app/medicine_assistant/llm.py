"""Rewriting an answer the catalogue already produced.

The model's whole job is wording. Which medicine, which field, what it says and
whether anything was found were all settled by a query before this module is
reached, and are handed over as structured data. Nothing here asks the model
what is true.

IT DOES NOT ROUTE, AND IT NEVER SEES A REFUSAL
----------------------------------------------
Unlike the scheduling assistant, there is no classification fallback. The
router is deterministic and stays that way; an unrecognised question gets the
deterministic reply rather than a model's opinion about what it might have
meant.

A refused question never reaches here at all. Its wording does not depend on
any data, and asking a model to phrase a refusal is asking it to negotiate one
— which is exactly the thing a patient trying to get advice would be probing
for.

TWO GATES, NOT ONE
------------------
The prompt forbids inventing dosage, safety or treatment. A prompt is a
request, so the existing guardrail runs over the output as well and replaces
anything containing a forbidden phrase. And whatever happens, the caller keeps
the deterministic sentence — a failure costs the phrasing, never the answer.

NO PROMPTS ARE STORED
---------------------
Not the question, not the reply. What is recorded is that a call happened, what
it was about, how long it took and what it cost.
"""

import json
import logging
import time

from app.config import get_settings
from app.core.metrics import (
    assistant_llm_failures_total,
    assistant_llm_latency_seconds,
    assistant_llm_requests_total,
    assistant_llm_tokens_total,
)
from app.integrations.openai_client import OpenAIClient
from app.services.medicine_ai_guardrail_service import validate_ai_response

logger = logging.getLogger(__name__)

# Shares the scheduling assistant's metric families, distinguished by label, so
# the two assistants' spend is separable without a second set of collectors.
PURPOSE = "medicine_format"

PROMPT_VERSION = "v2-format-1"

INSTRUCTIONS = """\
You write one short reply for a clinic's medicine information assistant.

You are given a JSON result produced by the clinic's own medicine catalogue.
Rewrite it as one or two plain sentences a patient would understand.

Rules:
- Use ONLY the values present in the JSON. Never add a fact that is not there.
- Never state or suggest a dose, a frequency, or how to take anything.
- Never say a medicine is safe or unsafe, suitable or unsuitable, for anyone —
  including during pregnancy, for children, or with other medicines.
- Never diagnose, never recommend a medicine, never suggest a treatment.
- If a field is missing, say plainly that the clinic has not recorded it. Do
  not substitute general knowledge.
- If several products match, list them and ask which was meant. Do not choose.
- Keep the disclaimer sentence if one is present in the payload.
- No greetings, no sign-offs, no emoji, no markdown.
"""


def is_enabled() -> bool:
    settings = get_settings()

    # A missing key disables it as surely as the flag does, so a
    # misconfiguration degrades exactly like the switch being off rather than
    # failing on every request.
    return bool(settings.ENABLE_MEDICINE_AI_FORMATTING and settings.OPENAI_API_KEY)


def _client() -> OpenAIClient:
    client = OpenAIClient()

    # The assistant's small model. There is no reasoning left to do here — the
    # catalogue decided every fact — so a larger one would cost more and be no
    # less bound by the payload it was given.
    client.model = get_settings().ASSISTANT_LLM_MODEL

    return client


def build_prompt(question: str, result: dict) -> str:
    return (
        f"{INSTRUCTIONS}\n"
        f"Patient asked: {question}\n\n"
        f"Catalogue result:\n{json.dumps(result, ensure_ascii=False, default=str)}\n\n"
        "Reply:"
    )


async def format_answer(question: str, result: dict) -> tuple[str | None, int, int]:
    """Phrase a computed answer.

    Returns the sentence (or None to use the deterministic one), the tokens
    spent and the latency in milliseconds — the caller records those and never
    the text.
    """
    if not is_enabled():
        return None, 0, 0

    assistant_llm_requests_total.labels(purpose=PURPOSE).inc()

    started = time.perf_counter()

    try:
        text, tokens = await _client().generate(build_prompt(question, result))

        elapsed = time.perf_counter() - started

        assistant_llm_latency_seconds.labels(purpose=PURPOSE).observe(elapsed)
        assistant_llm_tokens_total.labels(purpose=PURPOSE).inc(tokens or 0)

        cleaned = (text or "").strip()

        if not cleaned:
            return None, tokens or 0, int(elapsed * 1000)

        # Second gate. The prompt asks; this checks. Anything carrying a
        # forbidden phrase is replaced rather than shown.
        return validate_ai_response(cleaned), tokens or 0, int(elapsed * 1000)

    except Exception as exc:
        assistant_llm_failures_total.labels(
            purpose=PURPOSE, kind=type(exc).__name__
        ).inc()

        # The exception type only. A message can echo the prompt, and the
        # prompt contains whatever the patient typed.
        logger.warning(
            "medicine assistant formatting failed",
            extra={"error": type(exc).__name__},
        )

        return None, 0, int((time.perf_counter() - started) * 1000)

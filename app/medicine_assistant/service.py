"""Answering one question about a medicine.

    question -> router -> matcher -> tool -> structured JSON -> a sentence

No model is involved at this stage. The sentence is built from the same
structured result a model would later be handed, which is what makes formatting
optional rather than load-bearing: switch it off and the answer is less fluent
and exactly as correct.

WHAT IS RECORDED
----------------
The medicine matched, the intent, and the outcome. Never the question. A chat
box invites people to describe their health, and the surest way never to
mishandle that text is never to keep it — so what survives is what the
analytics actually read: which medicines are asked about, how often nothing
matches, how often we refuse.

A REFUSED QUESTION RECORDS NO MEDICINE
--------------------------------------
Not because none was mentioned, but because one usually was. Storing it would
leave a row saying which drug a pregnant patient asked about — the inference
this assistant exists to avoid, written down as a side effect of declining to
answer.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.quota import check_llm_quota
from app.core.metrics import (
    assistant_llm_refused_total,
    medicine_assistant_not_found_total,
    medicine_assistant_queries_total,
    medicine_assistant_success_total,
)
from app.medicine_assistant import llm
from app.medicine_assistant.dispatcher import dispatch
from app.medicine_assistant.responses import build_message
from app.medicine_assistant.router import MedicineIntent, route
from app.services.medicine_ai_log_service import create_ai_log
from app.services.medicine_assistant_query_service import (
    log_medicine_assistant_query,
)


async def answer_medicine_question_v2(
    db: AsyncSession,
    *,
    clinic_id: int,
    question: str,
    client_ip: str = "unknown",
) -> dict:
    """The assistant's reply, with the data it was built from.

    Returns both so the caller can render actions from the structure, a model
    can later phrase the same payload, and any claim can be checked against its
    source.
    """
    medicine_assistant_queries_total.inc()

    routed = route(question)

    result = await dispatch(db, routed, question)

    status = result.get("status")

    if status == "ok":
        medicine_assistant_success_total.inc()
    elif status == "not_found":
        medicine_assistant_not_found_total.inc()

    await log_medicine_assistant_query(
        db,
        clinic_id=clinic_id,
        # None for a refusal even when the question named one. See the module
        # docstring.
        medicine_name=(
            (result.get("medicine") or {}).get("brand_name")
            if status != "refused"
            else None
        ),
        intent=routed.intent.value,
        status=status,
    )

    deterministic = build_message(result, routed.intent)

    message, formatted_by, unavailable = await _maybe_format(
        db,
        clinic_id=clinic_id,
        client_ip=client_ip,
        question=question,
        result=result,
        deterministic=deterministic,
        answerable=is_answerable(routed.intent),
    )

    return {
        "message": message,
        "intent": routed.intent.value,
        "result": result,
        "formatted_by": formatted_by,
        "refusal_reason": result.get("refusal_reason"),
        "llm_unavailable_reason": unavailable,
    }


async def _maybe_format(
    db: AsyncSession,
    *,
    clinic_id: int,
    client_ip: str,
    question: str,
    result: dict,
    deterministic: str,
    answerable: bool,
) -> tuple[str, str, str | None]:
    """Phrase the answer with a model, if that is possible and worth doing.

    Returns the message, who wrote it, and why a model was not used when one
    was wanted. The deterministic sentence is the floor: nothing here can make
    the reply worse than the one already computed.
    """
    if not answerable:
        # A refusal or an unrecognised question. The wording depends on no
        # data, so there is nothing to format — and asking a model to phrase a
        # refusal is asking it to negotiate one.
        return deterministic, "backend", None

    if not llm.is_enabled():
        return deterministic, "backend", None

    decision = await check_llm_quota(ip=client_ip, clinic_id=clinic_id)

    if not decision:
        assistant_llm_refused_total.labels(reason=decision.reason).inc()

        return deterministic, "backend", decision.reason

    text, tokens, latency_ms = await llm.format_answer(question, result)

    if text is None:
        # Switched off mid-flight, empty, or the call failed. The answer stands.
        return deterministic, "backend", None

    medicine = result.get("medicine") or {}

    # Tokens and latency, never the prompt or the reply.
    await create_ai_log(
        db=db,
        clinic_id=clinic_id,
        medicine_id=medicine.get("id"),
        medicine_name=medicine.get("brand_name"),
        prompt_version=llm.PROMPT_VERSION,
        tokens_used=tokens,
        latency_ms=latency_ms,
    )

    return text, "llm", None


def is_answerable(intent: MedicineIntent) -> bool:
    """Whether an intent reaches the catalogue at all.

    Used by the layer above to decide there is nothing worth spending a model
    call on: a refusal's wording does not depend on any data.
    """
    return intent not in (MedicineIntent.REFUSE, MedicineIntent.UNKNOWN)

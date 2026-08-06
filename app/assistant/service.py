"""Answering one question.

    question -> router -> tool -> structured result -> (optionally) a sentence

The order is the guarantee. The backend decides what is true and the model, if
it is consulted at all, only says it in words. Every step below can be removed
and the assistant still answers — less fluently, never less correctly.

WHERE THE MODEL IS ALLOWED IN
-----------------------------
Two places, both narrow.

Formatting: after a tool has produced a result. The facts are already fixed;
the model rewrites them. A failure here costs the sentence, not the answer.

Classification: only when the deterministic router could not place the question
at all, and only to choose from a fixed list of intents. It never picks the
tool directly — its answer is fed back through the same dispatcher as any other
intent, so it can reach nothing a rule could not.

Neither path can query anything. The model sees a question and a JSON result;
it has no session, no clinic, no database.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant import llm
from app.assistant.dispatcher import dispatch
from app.assistant.quota import check_llm_quota
from app.assistant.router import Intent, RoutedIntent, route
from app.core.metrics import (
    assistant_llm_refused_total,
    assistant_requests_total,
)
from app.models.clinic import Clinic

BUDGET_MESSAGE = (
    "The AI assistant is temporarily unavailable. Please try again later."
)

UNSUPPORTED_MESSAGE = (
    "I can only help with appointments, doctors and clinic information."
)


async def answer(
    db: AsyncSession,
    clinic: Clinic,
    question: str,
    *,
    client_ip: str,
) -> dict:
    """The assistant's reply, always including the data it was built from.

    The structured result is returned alongside any sentence, not instead of
    it. The chat UI renders the sentence; the Book Appointment button needs the
    slot id underneath it; and anything reviewing what the assistant said can
    see exactly what it was given.
    """
    routed = route(question)

    # Tracked separately. The model may classify a question and then fail to
    # phrase the answer, and reporting that as "formatted by llm" would
    # misdescribe a reply the backend actually wrote.
    classified_by_llm = False
    formatted_by_llm = False
    llm_refused = ""

    # --- classification, only when the rules could not place the question ---
    if not routed.is_known and llm.is_enabled():
        decision = await check_llm_quota(ip=client_ip, clinic_id=clinic.id)

        if decision:
            guessed = await llm.classify(question)

            if guessed is not None and guessed is not Intent.UNKNOWN:
                # Fed back through the same dispatcher as a rule-matched
                # intent. The model names an intent; it never names a tool.
                routed = RoutedIntent(guessed, matched_on="llm classification")
                classified_by_llm = True
        else:
            llm_refused = decision.reason
            assistant_llm_refused_total.labels(reason=decision.reason).inc()

    result = await dispatch(db, clinic, routed)

    # --- formatting, only over a result the backend already computed --------
    message = None

    if llm.is_enabled() and not llm_refused:
        decision = await check_llm_quota(ip=client_ip, clinic_id=clinic.id)

        if decision:
            message = await llm.format_answer(question, result)
            formatted_by_llm = message is not None
        else:
            llm_refused = decision.reason
            assistant_llm_refused_total.labels(reason=decision.reason).inc()

    if message is None:
        message = _fallback_message(result, llm_refused)

    assistant_requests_total.labels(
        intent=routed.intent.value,
        path="llm" if (classified_by_llm or formatted_by_llm) else "deterministic",
    ).inc()

    return {
        "message": message,
        "intent": routed.intent.value,
        # The data the message was built from. Kept so the UI can render
        # actions from it and so an answer can always be checked against its
        # source.
        "result": result,
        "formatted_by": "llm" if formatted_by_llm else "backend",
        "classified_by": "llm" if classified_by_llm else "router",
        # Present only when the model was wanted and refused, so the caller can
        # tell a degraded reply from a normal one.
        "llm_unavailable_reason": llm_refused or None,
    }


def _fallback_message(result: dict, refused_reason: str) -> str:
    """A plain sentence built without a model.

    This is what the assistant says when the model is switched off, out of
    budget, or broken — and it is what makes those three survivable. It is
    written from the same structured result, so it can be wrong only in the way
    the data is wrong.
    """
    if refused_reason == "daily_budget_exceeded":
        return BUDGET_MESSAGE

    status = result.get("status")

    if status == "unsupported":
        return UNSUPPORTED_MESSAGE

    if status == "empty":
        return "I couldn't find any available doctor."

    if status == "not_found":
        return "I couldn't find that doctor at this clinic."

    if status == "ambiguous":
        names = ", ".join(c["name"] for c in result.get("candidates", []))
        return f"There is more than one match: {names}. Which did you mean?"

    if status == "unresolved_specialization":
        offered = ", ".join(
            s["specialization"] for s in result.get("specializations", [])
        )
        requested = result.get("requested")

        if not offered:
            return "This clinic has no doctors listed yet."

        return (
            f"I couldn't find a {requested} specialist here. "
            f"This clinic offers: {offered}."
        )

    if result.get("tool") == "clinic_information":
        return _clinic_sentence(result)

    # status == "ok". The structured result carries the detail; a caller
    # without the model renders it rather than reading a sentence.
    return "Here is what I found."


def _clinic_sentence(result: dict) -> str:
    """Contact details and hours, said from what is actually recorded.

    clinic_information answers address, phone and opening hours together,
    and its status describes only the HOURS. Mapping that status straight to a
    sentence answered "what is your phone number?" with "I don't have opening
    hours recorded" — unhelpful, and about a different question entirely.

    So the sentence is built from what is present. Missing hours are mentioned
    as a qualifier rather than as the whole answer.
    """
    contact = result.get("contact") or {}

    parts = []

    if contact.get("phone"):
        parts.append(f"Phone: {contact['phone']}")

    if contact.get("address"):
        parts.append(f"Address: {contact['address']}")

    open_now = (result.get("open_now") or {}).get("is_open")

    if open_now is True:
        parts.append("The clinic is open now")
    elif open_now is False:
        parts.append("The clinic is closed right now")
    else:
        # None means no hours were ever recorded — said plainly, because
        # "closed" would turn a gap in the data into a statement of fact.
        parts.append("Opening hours have not been recorded for this clinic")

    return ". ".join(parts) + "." if parts else "Here is what I found."

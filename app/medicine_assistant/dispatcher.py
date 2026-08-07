"""Turning a classified question into a tool result.

The router says what was asked; this decides which tool answers it and hands
back structured data. The two are separate because the first needs no database
and the second needs nothing else.

A REFUSAL NEVER REACHES THE DATABASE
------------------------------------
It returns before any lookup. "I'm pregnant, can I take Napa?" names a real
medicine, so a refusal that still resolved the subject would leave a record of
which drug a pregnant patient asked about — the exact inference this assistant
is built to avoid making, produced as a side effect of declining to answer.

There is nothing to look up anyway: the reply does not depend on the medicine.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.medicine_assistant.matching import MatchConfidence, resolve_subject
from app.medicine_assistant.router import (
    MedicineIntent,
    RoutedMedicineIntent,
)
from app.medicine_assistant.tools import (
    SCHEMA_VERSION,
    INTENT_FIELDS,
    ToolStatus,
    brands_of_generic,
    medicine_detail,
    medicine_field,
)


def _non_tool_envelope(status: str, **extra) -> dict:
    """The same shape the tools return, for outcomes no tool produced.

    Refusals and unclassified questions still have to be reported in the
    contract every caller reads, or each of them grows a second code path for
    the answers that never touched the database.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": None,
        "status": status,
        "medicine": None,
        "field": None,
        "value": None,
        "candidates": [],
        "confidence": MatchConfidence.NONE.value,
        "generic_name": None,
        "disclaimer_required": False,
        **extra,
    }


async def dispatch(
    db: AsyncSession,
    routed: RoutedMedicineIntent,
    question: str,
) -> dict:
    """Answer a classified question from the catalogue.

    `question` is passed through to the matcher, which reads the whole sentence
    to find a medicine in it. The router deliberately does not extract the name
    itself — that needs the catalogue.
    """
    if routed.intent is MedicineIntent.REFUSE:
        # Before any query. See the module docstring.
        return _non_tool_envelope(
            "refused",
            refusal_reason=(
                routed.refusal_reason.value if routed.refusal_reason else None
            ),
        )

    if routed.intent is MedicineIntent.UNKNOWN:
        return _non_tool_envelope("unknown")

    match = await resolve_subject(db, question)

    if routed.intent is MedicineIntent.BRANDS_OF_GENERIC:
        return await brands_of_generic(db, match, routed.subject_phrase)

    if routed.intent is MedicineIntent.MEDICINE_OVERVIEW:
        return medicine_detail(match)

    if routed.intent in INTENT_FIELDS:
        return medicine_field(match, routed.intent)

    # An intent with no tool behind it. Reported rather than guessed at, so
    # adding one without wiring it fails visibly instead of silently answering
    # something else.
    return _non_tool_envelope("unknown")


def status_of(result: dict) -> str:
    return result.get("status", ToolStatus.NOT_FOUND.value)

"""The only things the medicine assistant can ask the database.

Three read-only functions returning structured data. No prompts, no model
calls, no routing, and no English — a tool that returned a sentence would be
deciding how something is said, which is the one job the model has.

EVERY RESULT CARRIES A STATUS
-----------------------------
ok, not_found, ambiguous, field_missing. The caller branches on that rather
than on the shape of the payload.

field_missing is deliberately distinct from not_found. "We have Napa but no
storage guidance recorded" and "we have no Napa" are different facts, and a
reply that blurred them would tell someone their medicine does not exist
because one column is empty.

NOTHING IS INVENTED
-------------------
Every value is a column. There is no field for interactions, pregnancy safety,
dosing or contraindications, so the assistant cannot produce them however it is
asked — the absence is structural, not a matter of the prompt holding.
"""

from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.medicine_assistant.matching import (
    MatchConfidence,
    MatchStatus,
    MatchResult,
)
from app.medicine_assistant.router import MedicineIntent
from app.models.generic import Generic
from app.models.medicine import Medicine

# Bumped when the shape below changes in a way a consumer would notice. The
# frontend and the prompt both read this payload, and a silent reshape is how
# one of them starts rendering nothing.
SCHEMA_VERSION = 1

MAX_BRANDS = 12


class ToolStatus(str, Enum):
    OK = "ok"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    FIELD_MISSING = "field_missing"


# Which column answers which intent. The single place the mapping lives, so an
# intent cannot quietly start reading a different column than it names.
INTENT_FIELDS: dict[MedicineIntent, str] = {
    MedicineIntent.GENERIC_NAME: "generic_name",
    MedicineIntent.COMMON_USE: "common_use",
    MedicineIntent.SIDE_EFFECTS: "common_side_effects",
    MedicineIntent.STORAGE: "storage_guidance",
    MedicineIntent.MANUFACTURER: "manufacturer",
    MedicineIntent.DOSAGE_FORM: "dosage_form",
    MedicineIntent.STRENGTH: "strength",
    MedicineIntent.CATEGORY: "category",
    MedicineIntent.BRAND_OR_GENERIC: "is_brand",
}


def _medicine_payload(medicine: Medicine) -> dict:
    """The product, as the assistant is allowed to describe it.

    An explicit projection rather than the ORM row: a column added later for an
    unrelated reason must not start appearing in public answers because
    something serialised the whole object.
    """
    return {
        "id": medicine.id,
        "brand_name": medicine.name,
        "generic_name": medicine.generic_name,
        "strength": medicine.strength,
        "dosage_form": medicine.dosage_form,
        "manufacturer": medicine.manufacturer,
        "category": medicine.category,
        "is_brand": medicine.is_brand,
    }


def _envelope(
    tool: str,
    status: ToolStatus,
    *,
    medicine: Medicine | None = None,
    field: str | None = None,
    value=None,
    candidates: list[Medicine] | None = None,
    confidence: MatchConfidence = MatchConfidence.NONE,
    generic_name: str | None = None,
    extra: dict | None = None,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": tool,
        "status": status.value,
        "medicine": _medicine_payload(medicine) if medicine else None,
        "field": field,
        "value": value,
        "candidates": [_medicine_payload(c) for c in (candidates or [])],
        "confidence": confidence.value,
        "generic_name": generic_name,
        # Set whenever medicine information is returned. The catalogue is a
        # reference, not clinical advice, and the reply has to say so.
        "disclaimer_required": status
        in (ToolStatus.OK, ToolStatus.FIELD_MISSING),
        **(extra or {}),
    }


def _from_unresolved(tool: str, match: MatchResult) -> dict | None:
    """The envelope for a subject that could not be pinned to one product."""
    if match.status is MatchStatus.NOT_FOUND:
        return _envelope(
            tool,
            ToolStatus.NOT_FOUND,
            confidence=match.confidence,
            generic_name=match.generic_name,
        )

    if match.status is MatchStatus.AMBIGUOUS:
        return _envelope(
            tool,
            ToolStatus.AMBIGUOUS,
            candidates=match.candidates,
            confidence=match.confidence,
            generic_name=match.generic_name,
        )

    return None


def medicine_detail(match: MatchResult) -> dict:
    """Everything the catalogue records about one product.

    Answers "What is Napa Extra?" and "Tell me about Cef-3."
    """
    unresolved = _from_unresolved("medicine_detail", match)

    if unresolved is not None:
        return unresolved

    return _envelope(
        "medicine_detail",
        ToolStatus.OK,
        medicine=match.medicine,
        confidence=match.confidence,
        generic_name=match.generic_name,
        extra={
            # The long-form fields, kept out of the compact medicine payload so
            # a field question does not carry the whole record with it.
            "common_use": match.medicine.common_use,
            "common_side_effects": match.medicine.common_side_effects,
            "storage_guidance": match.medicine.storage_guidance,
        },
    )


def medicine_field(match: MatchResult, intent: MedicineIntent) -> dict:
    """One recorded property of one product.

    Returns field_missing rather than not_found when the product exists and the
    column is empty — telling someone their medicine does not exist because one
    field was never filled in would be a different and worse answer.
    """
    unresolved = _from_unresolved("medicine_field", match)

    if unresolved is not None:
        return unresolved

    column = INTENT_FIELDS.get(intent)

    if column is None:
        # An intent with no column behind it. Reported rather than guessed at,
        # so adding an intent without a field fails visibly.
        return _envelope(
            "medicine_field",
            ToolStatus.FIELD_MISSING,
            medicine=match.medicine,
            confidence=match.confidence,
        )

    value = getattr(match.medicine, column, None)

    # is_brand is a boolean: False is a real answer, not a missing one.
    missing = value is None or (isinstance(value, str) and not value.strip())

    return _envelope(
        "medicine_field",
        ToolStatus.FIELD_MISSING if missing else ToolStatus.OK,
        medicine=match.medicine,
        field=column,
        value=None if missing else value,
        confidence=match.confidence,
        generic_name=match.generic_name,
    )


async def brands_of_generic(
    db: AsyncSession,
    match: MatchResult,
    subject_phrase: str | None = None,
) -> dict:
    """The products a clinic can dispense for one substance.

    Answers "What brands contain Cefixime?". Works from either direction: the
    question may name the substance, or a brand whose substance is then used.
    """
    generic: Generic | None = None

    if match.medicine is not None and match.medicine.generic_id:
        generic = await db.get(Generic, match.medicine.generic_id)

    elif match.generic_name:
        generic = (
            await db.execute(
                select(Generic).where(Generic.name == match.generic_name)
            )
        ).scalar_one_or_none()

    if generic is None:
        return _envelope(
            "brands_of_generic",
            ToolStatus.NOT_FOUND,
            confidence=match.confidence,
            generic_name=match.generic_name or subject_phrase,
        )

    brands = (
        await db.scalars(
            select(Medicine)
            .where(Medicine.generic_id == generic.id)
            .order_by(Medicine.name)
            .limit(MAX_BRANDS)
        )
    ).all()

    return _envelope(
        "brands_of_generic",
        ToolStatus.OK if brands else ToolStatus.NOT_FOUND,
        candidates=list(brands),
        confidence=match.confidence,
        generic_name=generic.name,
        extra={"brand_count": len(brands)},
    )

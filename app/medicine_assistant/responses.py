"""Saying the result out loud, without a model.

This is what the assistant replies when AI formatting is switched off, out of
budget, or broken — and it is what makes those three survivable rather than
outages. Every sentence is built from the same structured result a model would
have been given, so it can only be wrong in the way the data is wrong.

REFUSALS EXPLAIN THEMSELVES
---------------------------
The reason the router recorded decides the wording. One sentence for every
refusal would tell a patient asking about pregnancy the same thing as one
asking to be diagnosed, and neither would know what to do next. Each points at
a person who can actually help.

NOTHING HERE ADDS A FACT
------------------------
The templates insert recorded values and say plainly when one is absent. There
is no phrasing that turns a missing field into a reassurance.
"""

from app.medicine_assistant.router import MedicineIntent, RefusalReason

DISCLAIMER = (
    "This information is from the clinic's medicine catalogue and is for "
    "general reference only. It is not medical advice."
)

# What to say instead, per reason. Each names someone who can help, because a
# refusal that only says no leaves the person exactly where they started.
REFUSAL_MESSAGES: dict[RefusalReason, str] = {
    RefusalReason.PERSONAL_MEDICAL_CONTEXT: (
        "I can only look up information about medicines in this clinic's "
        "catalogue, and I can't advise on anyone's own health. Please speak "
        "to a doctor about your situation."
    ),
    RefusalReason.ADVICE_SOUGHT: (
        "I can't recommend or advise on medicines. I can tell you what the "
        "catalogue records about a specific medicine — please ask a doctor "
        "about what is right for you."
    ),
    RefusalReason.DOSAGE_ADVICE: (
        "I can't advise on how much of a medicine to take. Dosing depends on "
        "the person, and a doctor or pharmacist should decide it."
    ),
    RefusalReason.DRUG_INTERACTION: (
        "I can't advise on taking medicines together. Please ask a doctor or "
        "pharmacist, who can check this properly."
    ),
    RefusalReason.POPULATION_SAFETY: (
        "I can't advise on whether a medicine is suitable during pregnancy, "
        "for children, or while breastfeeding. Please ask a doctor."
    ),
}

FALLBACK_REFUSAL = (
    "I can only provide information about medicines in this clinic's "
    "catalogue. Please speak to a doctor for medical advice."
)

UNKNOWN_MESSAGE = (
    "I can look up medicines in this clinic's catalogue — what they contain, "
    "what they are used for, their side effects, storage and manufacturer. "
    "Which medicine would you like to know about?"
)

# How each field reads in a sentence. Keyed by column so it cannot drift from
# what the tool actually returned.
FIELD_PHRASES: dict[str, str] = {
    "generic_name": "The generic name of {name} is {value}.",
    "common_use": "{name} is commonly used for {value}.",
    "common_side_effects": "Common side effects of {name} include {value}.",
    "storage_guidance": "{name}: {value}.",
    "manufacturer": "{name} is manufactured by {value}.",
    "dosage_form": "{name} comes as {value}.",
    "strength": "{name} has a strength of {value}.",
    "category": "{name} is classified as {value}.",
}

FIELD_LABELS: dict[str, str] = {
    "generic_name": "generic name",
    "common_use": "common use",
    "common_side_effects": "side effect information",
    "storage_guidance": "storage guidance",
    "manufacturer": "manufacturer",
    "dosage_form": "dosage form",
    "strength": "strength",
    "category": "category",
    "is_brand": "brand or generic status",
}


def _with_disclaimer(text: str, result: dict) -> str:
    if not result.get("disclaimer_required"):
        return text

    return f"{text} {DISCLAIMER}"


def _name(result: dict) -> str:
    medicine = result.get("medicine") or {}

    return medicine.get("brand_name") or "This medicine"


def _candidate_names(result: dict) -> str:
    return ", ".join(c["brand_name"] for c in result.get("candidates", []))


def _ambiguous(result: dict) -> str:
    """A substance with several products behind it.

    Named rather than answered: the brands of one substance do not agree — the
    Cefixime products in this catalogue record six different side-effect texts
    — so choosing one would be picking among them while sounding certain.
    """
    generic = result.get("generic_name") or "That"
    names = _candidate_names(result)

    return (
        f"{generic} is the active substance in several products here: {names}. "
        "Which one would you like to know about?"
    )


def _not_found(result: dict) -> str:
    generic = result.get("generic_name")

    if generic:
        # Known substance, nothing dispensable under it.
        return (
            f"{generic} is recorded as a substance, but there are no products "
            "listed under it in this clinic's catalogue."
        )

    return (
        "I couldn't find that medicine in this clinic's catalogue. It may be "
        "listed under a different brand name."
    )


def _field_missing(result: dict) -> str:
    """The medicine exists; this particular field was never filled in.

    Said as exactly that. Reporting it as "not found" would tell someone their
    medicine does not exist because one column is empty.
    """
    label = FIELD_LABELS.get(result.get("field") or "", "that information")

    return f"{_name(result)} is in the catalogue, but no {label} is recorded for it."


def _brand_or_generic(result: dict) -> str:
    is_brand = result.get("value")

    if is_brand:
        return f"{_name(result)} is a brand-name product."

    return f"{_name(result)} is listed as a generic product."


def _field_answer(result: dict) -> str:
    column = result.get("field")

    if column == "is_brand":
        return _brand_or_generic(result)

    template = FIELD_PHRASES.get(column or "")

    if template is None:
        # No phrasing for a field that was nonetheless answered. Better to
        # state it plainly than to omit an answer the database gave.
        label = FIELD_LABELS.get(column or "", "information")
        return f"{_name(result)} — {label}: {result.get('value')}."

    return template.format(name=_name(result), value=result.get("value"))


def _overview(result: dict) -> str:
    medicine = result.get("medicine") or {}

    parts = [f"{medicine.get('brand_name')}"]

    if medicine.get("strength"):
        parts.append(medicine["strength"])

    opening = " ".join(parts)

    details = []

    if medicine.get("generic_name"):
        details.append(f"contains {medicine['generic_name']}")

    if medicine.get("dosage_form"):
        details.append(f"comes as {medicine['dosage_form'].lower()}")

    if medicine.get("manufacturer"):
        details.append(f"is made by {medicine['manufacturer']}")

    sentence = f"{opening} {', '.join(details)}." if details else f"{opening}."

    if result.get("common_use"):
        sentence += f" It is commonly used for {result['common_use']}."

    if result.get("common_side_effects"):
        sentence += f" Common side effects include {result['common_side_effects']}."

    if result.get("storage_guidance"):
        sentence += f" {result['storage_guidance']}."

    return sentence


def _brands(result: dict) -> str:
    generic = result.get("generic_name") or "That substance"
    names = _candidate_names(result)
    count = result.get("brand_count", len(result.get("candidates", [])))

    return f"This clinic lists {count} product(s) containing {generic}: {names}."


def build_message(result: dict, intent: MedicineIntent) -> str:
    """A plain sentence for a result, built without a model."""
    status = result.get("status")

    if status == "refused":
        reason = result.get("refusal_reason")

        try:
            return REFUSAL_MESSAGES[RefusalReason(reason)]
        except (ValueError, KeyError):
            return FALLBACK_REFUSAL

    if status == "unknown":
        return UNKNOWN_MESSAGE

    if status == "ambiguous":
        return _with_disclaimer(_ambiguous(result), result)

    if status == "not_found":
        return _not_found(result)

    if status == "field_missing":
        return _with_disclaimer(_field_missing(result), result)

    # status == "ok"
    if result.get("tool") == "brands_of_generic":
        return _with_disclaimer(_brands(result), result)

    if intent is MedicineIntent.MEDICINE_OVERVIEW:
        return _with_disclaimer(_overview(result), result)

    return _with_disclaimer(_field_answer(result), result)

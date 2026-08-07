"""Deciding what was asked about a medicine, without asking a model.

Text in, intent out. No database, no clock, no model. Every rule below can be
checked by writing a sentence and asserting an intent, which is the whole
reason this is separate from the code that answers.

REFUSAL RUNS FIRST
------------------
Before any field is identified and before any lookup happens. "I'm pregnant,
can I take Napa?" contains a real medicine name and a recognisable question
shape; classified in the other order it would route to a lookup and be answered.
A refusal here costs no query and no tokens, and cannot be talked past.

WHY NOT A KEYWORD BLOCKLIST
---------------------------
The obvious approach is a list of forbidden words, and it does not work. The
existing (dead) blocklist in medicine_ai_safety_service contains "dosage", and
"What dosage form is Ace?" is a SUPPORTED question. It also contains "take",
"safe" and "child" — all of which appear in sentences that are perfectly
answerable.

The distinction is not vocabulary, it is who the sentence is about. So the
rules match CONSTRUCTIONS:

  - the patient describing themselves        "I have diabetes", "my child"
  - asking for advice about themselves       "can I take", "should I use"
  - asking about combining medicines         "with", "together", "interaction"
  - asking about a population's safety       "during pregnancy", "for children"

A question about a medicine's recorded properties matches none of these, and a
request for advice matches at least one whatever words it is dressed in.

PRECEDENCE
----------
Specific fields before the general overview: "What is the generic of Napa?"
contains "what is", which also opens "What is Napa?". The order is asserted in
the tests, because a reordering that looks harmless is how a question about a
generic name starts returning a product description.
"""

import re
from dataclasses import dataclass
from enum import Enum


class MedicineIntent(str, Enum):
    MEDICINE_OVERVIEW = "medicine_overview"
    GENERIC_NAME = "generic_name"
    COMMON_USE = "common_use"
    SIDE_EFFECTS = "side_effects"
    STORAGE = "storage"
    MANUFACTURER = "manufacturer"
    DOSAGE_FORM = "dosage_form"
    STRENGTH = "strength"
    CATEGORY = "category"
    BRAND_OR_GENERIC = "brand_or_generic"
    BRANDS_OF_GENERIC = "brands_of_generic"
    REFUSE = "refuse"
    UNKNOWN = "unknown"


class RefusalReason(str, Enum):
    """Why a question was refused, so the reply can say something useful."""

    PERSONAL_MEDICAL_CONTEXT = "personal_medical_context"
    ADVICE_SOUGHT = "advice_sought"
    DOSAGE_ADVICE = "dosage_advice"
    DRUG_INTERACTION = "drug_interaction"
    POPULATION_SAFETY = "population_safety"


@dataclass
class RoutedMedicineIntent:
    intent: MedicineIntent
    # The words the patient used for a substance, kept raw. Resolving "cancer"
    # or "Cefixime" to a catalogue row needs the database, which this layer
    # deliberately cannot see.
    subject_phrase: str | None = None
    refusal_reason: RefusalReason | None = None
    matched_on: str = ""

    @property
    def is_refusal(self) -> bool:
        return self.intent is MedicineIntent.REFUSE

    @property
    def is_known(self) -> bool:
        return self.intent not in (MedicineIntent.UNKNOWN, MedicineIntent.REFUSE)


# Checked BEFORE the refusal rules. "dosage form" is a property of a product;
# "what dosage should I take" is advice. Sharing the word "dosage" is the whole
# trap, and this is the exemption that keeps a supported question answerable.
ALLOWED_PHRASES = (
    "dosage form",
    "dose form",
    "pharmaceutical form",
)

# The patient describing their own body or family. The strongest signal, and
# the one that catches a question whose medicine name would otherwise make it
# look answerable.
_PERSONAL_CONTEXT = (
    r"\bi have\b",
    r"\bi've got\b",
    r"\bi am (?:a )?(?:pregnant|diabetic|hypertensive|allergic)\b",
    r"\bi'm (?:pregnant|diabetic|hypertensive|allergic)\b",
    r"\bi suffer\b",
    r"\bmy (?:child|son|daughter|baby|kid|wife|husband|mother|father)\b",
    r"\bmy (?:blood pressure|sugar|diabetes|condition|symptoms?)\b",
    r"\bi (?:feel|am feeling)\b",
)

# Asking what THEY should do, rather than what a medicine IS.
_ADVICE_SOUGHT = (
    r"\bcan i (?:take|use|have|drink)\b",
    r"\bshould i (?:take|use|stop|start)\b",
    r"\bis (?:it|this|that) safe\b",
    r"\bsafe (?:for me|to take|during|in)\b",
    r"\bwhat should i\b",
    r"\bwhich medicine should\b",
    r"\brecommend\b",
    r"\bdiagnos\w*\b",
    r"\bprescribe\b",
    r"\btreat(?:ment)? for\b",
    r"\bcure\b",
)

_DOSAGE_ADVICE = (
    r"\bhow (?:much|many) should\b",
    r"\bhow often should\b",
    r"\bwhat dose should\b",
    r"\bhow many (?:tablets?|pills?|times)\b",
    r"\bcorrect dosage\b",
    r"\bright dose\b",
)

_DRUG_INTERACTION = (
    r"\bcombine\b",
    r"\binteract\w*\b",
    r"\btogether with\b",
    r"\bmix(?:ed)? with\b",
    r"\balong with\b",
    r"\bat the same time as\b",
)

_POPULATION_SAFETY = (
    r"\bduring pregnancy\b",
    r"\bwhile pregnant\b",
    r"\bfor (?:children|kids|babies|infants|toddlers)\b",
    r"\bwhile breastfeeding\b",
    r"\bfor pregnant\b",
)

# Most specific first. ADVICE_SOUGHT is the broadest — "should I take" and
# "safe to..." appear inside dosage and pregnancy questions too — so checked
# earlier it swallows them and both get the generic reply. The reason exists to
# make the refusal say something useful; ordering it away wastes that.
#
# Every question here is refused either way. The order decides only WHICH
# sentence comes back, and the tests assert all five are distinguishable.
_REFUSAL_RULES: tuple[tuple[RefusalReason, tuple[str, ...]], ...] = (
    (RefusalReason.DOSAGE_ADVICE, _DOSAGE_ADVICE),
    (RefusalReason.POPULATION_SAFETY, _POPULATION_SAFETY),
    (RefusalReason.DRUG_INTERACTION, _DRUG_INTERACTION),
    (RefusalReason.PERSONAL_MEDICAL_CONTEXT, _PERSONAL_CONTEXT),
    (RefusalReason.ADVICE_SOUGHT, _ADVICE_SOUGHT),
)

# Field intents, most specific first. Each entry is (intent, phrases).
_FIELD_RULES: tuple[tuple[MedicineIntent, tuple[str, ...]], ...] = (
    # Plural "brands" before the singular brand/generic question, so
    # "what brands contain Cefixime" is not read as "is this a brand".
    (
        MedicineIntent.BRANDS_OF_GENERIC,
        ("what brands", "which brands", "brands of", "brands contain",
         "brands that contain", "brands with"),
    ),
    (
        MedicineIntent.BRAND_OR_GENERIC,
        ("brand or generic", "generic or brand", "is it a brand",
         "is this a brand", "is it generic", "is this generic",
         "branded or"),
    ),
    (
        MedicineIntent.GENERIC_NAME,
        ("generic name", "generic of", "generic for", "what generic",
         "active ingredient", "active substance", "what is in"),
    ),
    (
        MedicineIntent.SIDE_EFFECTS,
        ("side effect", "side-effect", "adverse", "reactions"),
    ),
    (
        MedicineIntent.STORAGE,
        ("store", "storage", "keep it", "kept"),
    ),
    (
        MedicineIntent.MANUFACTURER,
        ("manufacturer", "manufactured", "manufacture", "who makes",
         "made by", "which company", "producer", "produced by"),
    ),
    (
        MedicineIntent.DOSAGE_FORM,
        ("dosage form", "dose form", "pharmaceutical form", "what form",
         "which form", "tablet or", "syrup or", "capsule or"),
    ),
    (
        MedicineIntent.STRENGTH,
        ("strength", "how many mg", "how much mg", "what mg", "potency"),
    ),
    (
        MedicineIntent.CATEGORY,
        ("category", "what class", "drug class", "what type of medicine",
         "what kind of medicine", "classification"),
    ),
    (
        MedicineIntent.COMMON_USE,
        ("used for", "use of", "used to", "what is it for", "common use",
         "indication", "treats", "what does it do", "purpose of",
         "good for", "works for"),
    ),
)

# Only reached when no field rule matched. Kept last because "what is" opens
# almost every question in the list above.
_OVERVIEW_PHRASES = (
    "what is",
    "what's",
    "tell me about",
    "information about",
    "info about",
    "details of",
    "details about",
    "describe",
    "explain",
    "about the medicine",
)

# "what brands contain Cefixime" -> "cefixime"
_SUBJECT_AFTER = re.compile(
    r"\b(?:brands?(?:\s+(?:of|contain|containing|that contain|with))?)\s+"
    r"([a-z0-9][a-z0-9 +\-]{1,60}?)\s*[?.!]*$",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _matches(text: str, patterns) -> str | None:
    for pattern in patterns:
        if re.search(pattern, text):
            return pattern
    return None


def _contains(text: str, phrases) -> str | None:
    for phrase in phrases:
        if phrase in text:
            return phrase
    return None


def _allowed_span(text: str) -> str | None:
    """An exempt phrase, checked before refusal.

    "What dosage form is Ace?" must survive rules written to catch "what dosage
    should I take". The exemption is narrow and explicit rather than an attempt
    to make the refusal patterns cleverer.
    """
    return _contains(text, ALLOWED_PHRASES)


def _refusal(text: str) -> tuple[RefusalReason, str] | None:
    for reason, patterns in _REFUSAL_RULES:
        matched = _matches(text, patterns)

        if matched:
            return reason, matched

    return None


def _subject_phrase(text: str) -> str | None:
    match = _SUBJECT_AFTER.search(text)

    return match.group(1).strip() if match else None


def route(question: str) -> RoutedMedicineIntent:
    """Classify a question about a medicine, or refuse it, or decline to.

    UNKNOWN is a real outcome. A rule that guessed to avoid it would answer
    something nobody asked, and this assistant's value is that it only ever
    repeats what the catalogue records.
    """
    text = _normalize(question)

    if not text:
        return RoutedMedicineIntent(MedicineIntent.UNKNOWN)

    # --- refusal, before anything is identified or looked up ---------------
    exempt = _allowed_span(text)

    if not exempt:
        refused = _refusal(text)

        if refused:
            reason, pattern = refused

            return RoutedMedicineIntent(
                MedicineIntent.REFUSE,
                refusal_reason=reason,
                matched_on=pattern,
            )

    # --- which property is being asked about -------------------------------
    for intent, phrases in _FIELD_RULES:
        matched = _contains(text, phrases)

        if matched:
            return RoutedMedicineIntent(
                intent,
                subject_phrase=(
                    _subject_phrase(text)
                    if intent is MedicineIntent.BRANDS_OF_GENERIC
                    else None
                ),
                matched_on=matched,
            )

    # --- a general question about a medicine -------------------------------
    matched = _contains(text, _OVERVIEW_PHRASES)

    if matched:
        return RoutedMedicineIntent(
            MedicineIntent.MEDICINE_OVERVIEW, matched_on=matched
        )

    return RoutedMedicineIntent(MedicineIntent.UNKNOWN)

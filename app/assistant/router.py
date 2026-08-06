"""Working out what was asked, without asking a model.

Most of what a scheduling assistant is asked is a handful of questions in a
handful of shapes. "When do you close?", "is Dr Rahman free tomorrow?", "I need
a cardiologist" — these do not need a language model to recognise, and routing
them here rather than through one makes the assistant faster, cheaper, and
predictable enough to test.

The model is the fallback, not the front door. Anything this cannot classify
returns UNKNOWN and the caller decides whether to spend a model call on it.

PURE ON PURPOSE
---------------
Text in, intent out. No database, no clock, no clinic. A rule that reached for
the database would be a rule that could not be tested by writing a sentence and
asserting an intent, and this file's whole value is that it can be.

That is also why the specialization is returned as the RAW WORDS a patient
used. Deciding that "cancer specialist" means Oncology requires knowing what
the clinic actually practises, which is the dispatcher's job — a router that
guessed would invent specialties for clinics that do not have them.

PRECEDENCE MATTERS
------------------
"When is Dr Rahman free tomorrow?" contains "when", which also appears in "when
do you close?". Rules are ordered most specific first, and the order is
asserted in the tests, because a reordering that looks harmless is how "are you
open?" starts being answered with a doctor's schedule.
"""

import re
from dataclasses import dataclass, field
from enum import Enum


class Intent(str, Enum):
    DOCTOR_AVAILABILITY = "doctor_availability"
    EARLIEST_SLOT = "earliest_slot"
    LIST_SPECIALIZATIONS = "list_specializations"
    SEARCH_DOCTORS = "search_doctors"
    CLINIC_INFORMATION = "clinic_information"
    UNKNOWN = "unknown"


class DayReference(str, Enum):
    """A day named relative to the clinic's today.

    Kept symbolic rather than resolved to a date here: "tomorrow" depends on
    the clinic's timezone, and a router that reached for a clock would answer
    for the server's day. The dispatcher resolves it.
    """

    TODAY = "today"
    TOMORROW = "tomorrow"


@dataclass
class RoutedIntent:
    intent: Intent
    doctor_name: str | None = None
    specialization_text: str | None = None
    day: DayReference | None = None
    weekday: int | None = None
    matched_on: str = ""
    params: dict = field(default_factory=dict)

    @property
    def is_known(self) -> bool:
        return self.intent is not Intent.UNKNOWN


WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

# Words that end a name rather than continue one. Without this the capture
# runs into the question: "Dr Rahman available tomorrow" yields "rahman
# available", which matches no doctor, so a question about someone who exists
# is answered "not found".
_NAME_STOP = (
    r"(?:available|availability|free|is|are|on|at|in|for|to|the|a|an|"
    r"tomorrow|today|tonight|now|this|next|week|schedule|working|works|"
    r"when|what|which|time|and|or|please)"
)

# "Dr Rahman", "Dr. Rahman Khan", "doctor Rahman". At most two words, neither
# of which may be a stop word.
_DOCTOR_NAME = re.compile(
    rf"\b(?:dr|doctor)\.?\s+"
    rf"(?!{_NAME_STOP}\b)([a-z]+)"
    rf"(?:\s+(?!{_NAME_STOP}\b)([a-z]+))?",
    re.IGNORECASE,
)

_AVAILABILITY_WORDS = (
    "available",
    "availability",
    "free",
    "schedule",
    "when is",
    "when does",
    "what time is",
)

_EARLIEST_WORDS = (
    "earliest",
    "soonest",
    "as soon as",
    "first available",
    "next available",
    "who can see me",
    "anyone available",
    "any doctor available",
)

_CLINIC_INFO_WORDS = (
    "open",
    "close",
    "closing",
    "opening",
    "hours",
    "holiday",
    "address",
    "location",
    "where are you",
    "phone",
    "number",
    "contact",
    "email",
)

_SPECIALIZATION_QUESTION = (
    "specialist",
    "specialists",
    "specialty",
    "speciality",
    "specialities",
    "specialties",
    "specialization",
    "specializations",
    "department",
    "departments",
    "what kind of doctors",
    "what type of doctors",
)

_SEARCH_WORDS = (
    "i need",
    "i want",
    "looking for",
    "do you have",
    "is there",
    "find me",
    "any ",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _mentions(text: str, phrases) -> str | None:
    for phrase in phrases:
        if phrase in text:
            return phrase
    return None


def _day_reference(text: str) -> DayReference | None:
    # "tomorrow" checked first: "today" is a substring of nothing here, but the
    # two can both appear ("not today, tomorrow") and the later one is meant.
    if "tomorrow" in text:
        return DayReference.TOMORROW
    if "today" in text or "right now" in text or "tonight" in text:
        return DayReference.TODAY
    return None


def _weekday(text: str) -> int | None:
    for name, index in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", text):
            return index
    return None


def _doctor_name(text: str) -> str | None:
    match = _DOCTOR_NAME.search(text)

    if not match:
        return None

    parts = [part for part in match.groups() if part]

    return " ".join(parts) if parts else None


def _specialization_text(text: str) -> str | None:
    """The words a patient used for a specialty, not a specialty.

    "I need a cancer specialist" yields "cancer". Turning that into Oncology —
    or into nothing, at a clinic without one — needs the clinic's real list,
    which this layer deliberately cannot see.
    """
    patterns = (
        r"(?:i need|i want|looking for|find me)\s+(?:a|an|the)?\s*([a-z ]+?)"
        r"(?:\s+(?:specialist|doctor|please))?\s*[?.!]*$",
        r"(?:do you have|is there)\s+(?:a|an|any)?\s*([a-z ]+?)"
        r"(?:\s+(?:specialist|doctor|department))\b",
    )

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            candidate = match.group(1).strip()

            if candidate and candidate not in {"doctor", "a doctor", "an appointment"}:
                return candidate

    return None


def route(question: str) -> RoutedIntent:
    """Classify a question, or decline to.

    Returning UNKNOWN is a real outcome, not a failure: it is what hands the
    question to a model, and a rule that guessed to avoid it would produce a
    confident answer to something nobody asked.
    """
    text = _normalize(question)

    if not text:
        return RoutedIntent(Intent.UNKNOWN)

    doctor_name = _doctor_name(text)
    day = _day_reference(text)
    weekday = _weekday(text)

    # 1. A named doctor plus an availability word. Most specific, so it runs
    #    first: "when is Dr Rahman free?" also matches the clinic-hours words.
    if doctor_name and _mentions(text, _AVAILABILITY_WORDS):
        return RoutedIntent(
            Intent.DOCTOR_AVAILABILITY,
            doctor_name=doctor_name,
            day=day,
            weekday=weekday,
            matched_on="doctor name + availability",
        )

    # 2. Explicitly asking for the soonest, whoever it is with.
    if phrase := _mentions(text, _EARLIEST_WORDS):
        return RoutedIntent(
            Intent.EARLIEST_SLOT,
            specialization_text=_specialization_text(text),
            day=day,
            matched_on=phrase,
        )

    # 3. Questions about the premises. Before the doctor searches, because
    #    "are you open on Friday?" is about the clinic and mentions no doctor.
    if phrase := _mentions(text, _CLINIC_INFO_WORDS):
        return RoutedIntent(
            Intent.CLINIC_INFORMATION,
            day=day,
            weekday=weekday,
            matched_on=phrase,
        )

    # 4. "What specialists do you have?" — the closed list, not a doctor.
    if phrase := _mentions(text, _SPECIALIZATION_QUESTION):
        specialization = _specialization_text(text)

        # "Do you have a cancer specialist?" names one; "what specialists do
        # you have?" does not. The first is a search, the second is the list.
        if specialization:
            return RoutedIntent(
                Intent.SEARCH_DOCTORS,
                specialization_text=specialization,
                matched_on=f"{phrase} + named specialty",
            )

        return RoutedIntent(Intent.LIST_SPECIALIZATIONS, matched_on=phrase)

    # 5. Looking for someone, by name or by specialty.
    if _mentions(text, _SEARCH_WORDS) or doctor_name:
        return RoutedIntent(
            Intent.SEARCH_DOCTORS,
            doctor_name=doctor_name,
            specialization_text=_specialization_text(text),
            matched_on="search phrasing",
        )

    return RoutedIntent(Intent.UNKNOWN)

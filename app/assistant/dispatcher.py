"""Turning a classified question into a tool result.

The router says what was asked, in the patient's own words. This decides which
tool answers it and resolves those words against what the clinic actually has —
the two are separate because the first needs no database and the second needs
nothing else.

RESOLVING THE PATIENT'S WORDS
-----------------------------
A patient says "cancer specialist"; the record says "Oncology". Matching is
done against the clinic's REAL list of specializations, so a word can only ever
resolve to something that clinic practises. At a clinic without oncology,
"cancer" resolves to nothing and the answer is that they do not have one —
which is true, and is the answer a hardcoded synonym table would have got
wrong the moment it was out of date.

Only exact and containment matches are made. "cardiologist" contains
"cardiology" once both are trimmed to their stem, but "heart" does not, and
guessing that it should would be inventing clinical vocabulary. What this
cannot resolve is passed through as a free-text search instead, so the patient
gets the clinic's doctor list rather than a wrong specialty.

"TODAY" IS THE CLINIC'S TODAY
-----------------------------
The router returns "tomorrow" as a symbol rather than a date, because resolving
it needs the clinic's timezone. Done here, against clinic_today, so a patient
asking at 11pm in Dhaka is not answered for the server's yesterday.
"""

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.router import DayReference, Intent, RoutedIntent
from app.assistant.tools import (
    clinic_information,
    clinic_today,
    doctor_availability,
    earliest_slot,
    list_specializations,
    search_doctors,
)
from app.models.clinic import Clinic


def _stem(text: str) -> str:
    """Reduce a specialty word to something two spellings of it share.

    "Cardiology" and "cardiologist" both become "cardiolog". Crude, and
    deliberately so: anything cleverer starts mapping words that merely look
    similar onto different specialties.
    """
    word = (text or "").strip().lower()

    for suffix in ("ists", "ist", "ology", "ologist", "y", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]

    return word


async def resolve_specialization(
    db: AsyncSession,
    clinic: Clinic,
    text: str | None,
) -> str | None:
    """The clinic's own name for what the patient asked about, if it has one.

    Returns None when nothing matches — including when the clinic simply does
    not offer it. That is the honest outcome, and the caller reports it as
    "no", never as "did you mean...".
    """
    if not text:
        return None

    offered = await list_specializations(db, clinic)

    wanted = _stem(text)

    for entry in offered["specializations"]:
        name = entry["specialization"]
        candidate = _stem(name)

        if wanted == candidate or wanted in candidate or candidate in wanted:
            return name

    return None


def resolve_day(clinic: Clinic, day: DayReference | None):
    """A symbolic day as a real date in the clinic's calendar."""
    today = clinic_today(clinic)

    if day is DayReference.TOMORROW:
        return today + timedelta(days=1)

    return today


async def dispatch(
    db: AsyncSession,
    clinic: Clinic,
    routed: RoutedIntent,
) -> dict:
    """Run the tool this question calls for.

    An unclassified question returns a result of its own rather than raising:
    "I can't help with that" is an answer the assistant has to be able to give,
    and it is the only one available when nothing was understood.
    """
    if routed.intent is Intent.UNKNOWN:
        return {
            "tool": None,
            "clinic_id": clinic.id,
            "clinic_name": clinic.name,
            "status": "unsupported",
            "reason": "not_a_scheduling_question",
        }

    if routed.intent is Intent.CLINIC_INFORMATION:
        return clinic_information(clinic)

    if routed.intent is Intent.LIST_SPECIALIZATIONS:
        return await list_specializations(db, clinic)

    if routed.intent is Intent.DOCTOR_AVAILABILITY:
        return await doctor_availability(
            db,
            clinic,
            doctor_name=routed.doctor_name,
            on_date=resolve_day(clinic, routed.day),
            # A weekday with no day reference ("is Dr Rahman in on Friday?")
            # is a week's window rather than a guess at which Friday: the tool
            # returns the days it covers and the answer names the date.
            days=7 if routed.weekday is not None and routed.day is None else 1,
        )

    specialization = await resolve_specialization(
        db, clinic, routed.specialization_text
    )

    # A specialty was named and could not be matched to anything this clinic
    # practises. Deterministic matching cannot bridge every gap: "cardiologist"
    # and "Cardiology" share a stem, but "cancer" and "Oncology" share no
    # letters at all, and no amount of string work connects them.
    #
    # Reported as unresolved, with the clinic's real list attached, rather than
    # quietly run as a text search that returns nothing. Empty would read as
    # "we have no such doctor", which is right at a clinic without oncology and
    # WRONG at one with it. Naming what could not be matched lets the caller
    # answer honestly from the list, or hand the question to a model that can
    # map the word against those same options.
    if routed.specialization_text and not specialization:
        offered = await list_specializations(db, clinic)

        return offered | {
            "status": "unresolved_specialization",
            "requested": routed.specialization_text,
        }

    if routed.intent is Intent.EARLIEST_SLOT:
        return await earliest_slot(db, clinic, specialization=specialization)

    return await search_doctors(
        db,
        clinic,
        query=routed.doctor_name,
        specialization=specialization,
    )

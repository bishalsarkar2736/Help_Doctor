"""The only things the scheduling assistant can ask the backend.

Four read-only functions. Each takes a clinic that has ALREADY been resolved
and returns plain structured data — no prompts, no model calls, no routing.

WHY A TOOL LAYER AT ALL
-----------------------
The model does not choose what to fetch and cannot reach a session, a
repository or a query. It receives the output of one of these and phrases it.
That is what makes "the AI never invents availability" a property of the system
rather than an instruction in a prompt that a model may or may not follow.

THE CLINIC IS PASSED IN, NEVER LOOKED UP
----------------------------------------
Every tool takes a resolved Clinic rather than a clinic_id. A tool that took an
id could be called with one that never passed tenant resolution, and re-reading
it here would be a second place that could load a different clinic than the
request was scoped to. Passing the object means the tenancy decision was made
before this layer was reached.

EVERY RESULT CARRIES A STATUS
-----------------------------
"ok", "empty", "ambiguous", "not_found" or "unknown". The caller branches on
that rather than on the shape of the payload, and "empty" is a real answer that
must be relayed as "I couldn't find any available doctor" — never softened into
a nearby result.

NO PHI
------
Doctor names, specializations, free slots, clinic contact details and opening
hours. Nothing about any patient, no appointments, no records. A tool that
cannot read patient data cannot leak it, whatever it is asked.
"""

from datetime import date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.formatting import describe_slot
from app.core.tz import to_zoneinfo
from app.models.clinic import Clinic
from app.models.doctor import Doctor, DoctorStatus
from app.models.user import User
from app.services.clinic_information_service import (
    get_clinic_holiday_schedule,
    get_clinic_information,
    get_clinic_opening_hours,
    is_open_now,
)
from app.services.earliest_slot_service import find_earliest_available_doctor
from app.services.slot_service import get_doctor_slots

# Small on purpose. These answers are read aloud in a chat reply, and twenty
# doctors is a list nobody listens to. A patient who needs the full directory
# is better served by the directory page.
MAX_DOCTORS = 8
MAX_SLOTS = 12
MAX_EARLIEST = 3


def clinic_today(clinic: Clinic) -> date:
    """Today, as the clinic reckons it.

    date.today() is the SERVER's date. With the API in UTC and a clinic at
    UTC+6, the two disagree for six hours of every day — long enough for
    "who can see me today?" to answer for yesterday every evening.
    """
    return datetime.now(to_zoneinfo(clinic.timezone)).date()


def _envelope(tool: str, clinic: Clinic, status: str, **payload) -> dict:
    return {
        "tool": tool,
        "clinic_id": clinic.id,
        "clinic_name": clinic.name,
        "status": status,
        **payload,
    }


def _visible_doctor_filters():
    """Who a clinic will actually show a patient.

    Approved, with an active account. A pending or rejected doctor is not
    practising and a deactivated account cannot be consulted, so offering
    either sends someone to a person who will not see them. Matches what
    GET /doctors already enforces, so the assistant and the directory cannot
    disagree about who works there.
    """
    return (
        Doctor.status == DoctorStatus.APPROVED,
        User.is_active.is_(True),
    )


# ---------------------------------------------------------------------------
# search_doctors
# ---------------------------------------------------------------------------


async def search_doctors(
    db: AsyncSession,
    clinic: Clinic,
    *,
    query: str | None = None,
    specialization: str | None = None,
    limit: int = MAX_DOCTORS,
) -> dict:
    """Doctors at this clinic, by name or by specialization.

    Answers "I need a cardiologist" and "do you have a Dr Rahman?".
    """
    statement = (
        select(
            Doctor.id,
            Doctor.specialization,
            Doctor.experience_years,
            Doctor.consultation_fee,
            User.full_name,
        )
        .join(User, Doctor.user_id == User.id)
        .where(Doctor.clinic_id == clinic.id, *_visible_doctor_filters())
        .order_by(User.full_name)
        .limit(min(limit, MAX_DOCTORS))
    )

    if specialization:
        # Exact match, case-insensitive — the same comparison GET /doctors
        # makes, so "cardiologist" means the same thing in both places.
        statement = statement.where(
            func.lower(Doctor.specialization) == specialization.strip().lower()
        )

    if query:
        pattern = f"%{query.strip()}%"
        statement = statement.where(
            or_(User.full_name.ilike(pattern), Doctor.specialization.ilike(pattern))
        )

    rows = (await db.execute(statement)).all()

    return _envelope(
        "search_doctors",
        clinic,
        "ok" if rows else "empty",
        query=query,
        specialization=specialization,
        found=len(rows),
        doctors=[
            {
                "doctor_id": row.id,
                "name": row.full_name,
                "specialization": row.specialization,
                "experience_years": row.experience_years,
                "consultation_fee": (
                    float(row.consultation_fee)
                    if row.consultation_fee is not None
                    else None
                ),
            }
            for row in rows
        ],
    )


# ---------------------------------------------------------------------------
# list_specializations
# ---------------------------------------------------------------------------


async def list_specializations(db: AsyncSession, clinic: Clinic) -> dict:
    """Every specialization this clinic actually practises, with counts.

    Answers "do you have a cancer specialist?" — but indirectly, and that is
    the point.

    A patient says "cancer specialist"; the record says "Oncology". The two do
    not match as strings, so asking search_doctors for "cancer" comes back
    empty even at a clinic that has one. The gap is vocabulary, not data.

    Bridging it with a hardcoded table of lay terms would mean inventing
    clinical synonyms and maintaining them forever, and a wrong entry sends a
    patient to the wrong specialist. Instead this returns the clinic's real,
    CLOSED list, and the layer above matches the patient's words against it.
    Constrained to what exists, "cancer specialist" can resolve to Oncology at
    a clinic that has one and to nothing at a clinic that does not — which is
    the honest answer here, since this one has Cardiology and General Medicine.

    NOT a triage tool. Matching a patient's word for a SPECIALTY to its formal
    name is vocabulary. Matching a patient's SYMPTOM to a specialty is triage,
    and this assistant is explicitly not a diagnostic one — nothing here maps a
    complaint to a department.
    """
    rows = (
        await db.execute(
            select(Doctor.specialization, func.count(Doctor.id))
            .join(User, Doctor.user_id == User.id)
            .where(Doctor.clinic_id == clinic.id, *_visible_doctor_filters())
            .group_by(Doctor.specialization)
            .order_by(Doctor.specialization)
        )
    ).all()

    return _envelope(
        "list_specializations",
        clinic,
        "ok" if rows else "empty",
        found=len(rows),
        specializations=[
            {"specialization": name, "doctor_count": count} for name, count in rows
        ],
    )


# ---------------------------------------------------------------------------
# doctor_availability
# ---------------------------------------------------------------------------


async def _resolve_doctor(
    db: AsyncSession,
    clinic: Clinic,
    *,
    doctor_id: int | None,
    doctor_name: str | None,
):
    """The one doctor being asked about, or why there isn't one.

    A name can match more than one person. Picking the first would answer
    confidently about the wrong doctor, so an ambiguous name is reported as
    ambiguous and the caller asks which one was meant.
    """
    statement = (
        select(Doctor.id, Doctor.specialization, User.full_name)
        .join(User, Doctor.user_id == User.id)
        .where(Doctor.clinic_id == clinic.id, *_visible_doctor_filters())
    )

    if doctor_id is not None:
        statement = statement.where(Doctor.id == doctor_id)
    elif doctor_name:
        statement = statement.where(User.full_name.ilike(f"%{doctor_name.strip()}%"))
    else:
        return []

    return (await db.execute(statement.limit(5))).all()


async def doctor_availability(
    db: AsyncSession,
    clinic: Clinic,
    *,
    doctor_id: int | None = None,
    doctor_name: str | None = None,
    on_date: date | None = None,
    days: int = 1,
) -> dict:
    """When a named doctor is free, on the clinic's calendar days.

    Answers "is Dr Rahman available tomorrow?". `on_date` is a real date —
    turning "tomorrow" into one is the router's job, not this layer's, so that
    the date a patient hears is never inferred inside the same step that reads
    the database.
    """
    matches = await _resolve_doctor(
        db, clinic, doctor_id=doctor_id, doctor_name=doctor_name
    )

    if not matches:
        return _envelope(
            "doctor_availability",
            clinic,
            "not_found",
            requested=doctor_name or doctor_id,
        )

    if len(matches) > 1:
        return _envelope(
            "doctor_availability",
            clinic,
            "ambiguous",
            requested=doctor_name or doctor_id,
            candidates=[
                {
                    "doctor_id": row.id,
                    "name": row.full_name,
                    "specialization": row.specialization,
                }
                for row in matches
            ],
        )

    doctor = matches[0]
    tz = to_zoneinfo(clinic.timezone)

    # get_doctor_slots reads whole clinic-local days, so the day a patient
    # asked about is the day they get back.
    slots = await get_doctor_slots(
        db,
        doctor_id=doctor.id,
        start_date=on_date or clinic_today(clinic),
        days=days,
        only_available=True,
        limit=MAX_SLOTS,
    )

    described = [
        describe_slot(
            datetime.fromisoformat(slot["start_time"]),
            datetime.fromisoformat(slot["end_time"]),
            tz,
        )
        | {"slot_id": slot["id"]}
        for slot in slots
    ]

    return _envelope(
        "doctor_availability",
        clinic,
        "ok" if described else "empty",
        doctor={
            "doctor_id": doctor.id,
            "name": doctor.full_name,
            "specialization": doctor.specialization,
        },
        requested_date=(on_date or clinic_today(clinic)).isoformat(),
        days=days,
        found=len(described),
        slots=described,
    )


# ---------------------------------------------------------------------------
# earliest_slot
# ---------------------------------------------------------------------------


async def earliest_slot(
    db: AsyncSession,
    clinic: Clinic,
    *,
    specialization: str | None = None,
    limit: int = MAX_EARLIEST,
) -> dict:
    """The soonest anyone at this clinic can be seen.

    Answers "who can see me today?" and "I need the earliest appointment".
    Wraps find_earliest_available_doctor rather than repeating its query, so
    the rules about who may be offered live in one place.
    """
    tz = to_zoneinfo(clinic.timezone)

    results = await find_earliest_available_doctor(
        db,
        clinic_id=clinic.id,
        specialization=specialization,
        limit=min(limit, MAX_EARLIEST),
    )

    options = [
        {
            "slot_id": result["slot_id"],
            "doctor_id": result["doctor_id"],
            "doctor_name": result["doctor_name"],
            "specialization": result["specialization"],
            "consultation_fee": result["consultation_fee"],
            **describe_slot(
                datetime.fromisoformat(result["start_time"]),
                datetime.fromisoformat(result["end_time"]),
                tz,
            ),
        }
        for result in results
    ]

    return _envelope(
        "earliest_slot",
        clinic,
        "ok" if options else "empty",
        specialization=specialization,
        found=len(options),
        options=options,
    )


# ---------------------------------------------------------------------------
# clinic_information
# ---------------------------------------------------------------------------


def clinic_information(clinic: Clinic) -> dict:
    """Contact details, opening hours, holidays, and whether it is open now.

    Answers "what is your address?", "what time do you close?" and "are you
    open now?" in one call, because they are a single question about the same
    row and splitting them would mean three round trips for one reply.

    Synchronous: everything here is already on the clinic that tenant
    resolution loaded, so there is nothing further to read.
    """
    hours = get_clinic_opening_hours(clinic)
    open_now = is_open_now(clinic)

    return _envelope(
        "clinic_information",
        clinic,
        # Contact details are always known; the hours may not be, and the
        # caller has to be able to tell "closed" from "never recorded".
        "unknown" if not hours["is_configured"] else "ok",
        contact=get_clinic_information(clinic),
        opening_hours=hours,
        holidays=get_clinic_holiday_schedule(clinic),
        open_now=open_now,
    )

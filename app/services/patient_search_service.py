"""Finding a patient, within one clinic.

Patients are global identities on purpose: the same person may be treated at
more than one clinic, and duplicating them per tenant would split their history.
So a patient row carries no clinic_id, and "belongs to this clinic" has to be
derived rather than stored.

The relationship that defines it is an appointment. A patient belongs to a
clinic if they have at least one appointment there — which is the same thing a
receptionist means when they say "our patients".

WHY THIS EXISTS
---------------
Search was role-guarded and nothing more. Any admin, doctor or receptionist
could find any patient on the platform by name, email or phone, including
people with no relationship to their clinic. The audit log recorded it, so
trawling was detectable afterwards — but nothing prevented it.

THE CLINIC COMES FROM THE PRINCIPAL, NOT THE REQUEST
----------------------------------------------------
Never from a parameter. resolve_clinic_id returns the CALLER-SUPPLIED value
unchanged for receptionists, so scoping to it would let the search be pointed
at another tenant by editing a query string — defeating the filter it was added
to enforce.

THE FIRST-BOOKING EXCEPTION
---------------------------
Scoping alone deadlocks reception: a patient becomes findable by being booked,
and is booked by first being found. So an exact email or an exact phone reaches
a patient at any clinic, which is what lets the desk register a walk-in.

The identifier is the authorisation. You cannot discover anyone this way, only
confirm somebody whose full email or phone you were already given — the same
thing a receptionist has on a referral slip. What keeps that from being
enumeration is that it is equality and nothing else: partial and fuzzy matching
stay clinic-scoped, so "017" reaches nobody outside the clinic.

The disclosure is real and worth naming: an exact email returns that person's
name and phone number. It is recorded in the PHI access log like every other
surfaced patient.
"""

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.appointment import Appointment
from app.models.patient import Patient
from app.models.user import User
from app.schemas.patient_search import PatientSearchOut


async def search_patients(
    *,
    db: AsyncSession,
    clinic_id: int,
    q: str,
    limit: int = 20,
    offset: int = 0,
) -> list[PatientSearchOut]:
    """
    Search patients by:

    - Full name
    - Email
    - Phone number

    Restricted to patients with at least one appointment at `clinic_id`.
    Results are paginated.
    """
    # EXISTS rather than a join: a patient with six appointments here is still
    # one patient, and a join would return them six times. DISTINCT would also
    # work, but then the ORDER BY column has to appear in the select list and
    # the query stops saying what it means. This reads as the rule does —
    # "has at least one appointment at this clinic".
    belongs_to_clinic = exists().where(
        Appointment.patient_id == Patient.user_id,
        Appointment.clinic_id == clinic_id,
    )

    q = q.strip()

    # THE FIRST-BOOKING EXCEPTION
    #
    # Scoping alone deadlocks reception: a patient becomes findable by being
    # booked, and is booked by first being found. Somebody walking in for the
    # first time is invisible to the desk trying to register them.
    #
    # So a caller who already holds a patient's full email or phone may reach
    # them regardless of clinic. The identifier is the authorisation: you
    # cannot discover someone this way, only confirm a person you were already
    # given. Partial and fuzzy matching stay clinic-scoped, which is what keeps
    # this from being enumeration — "017" reaches nobody outside the clinic
    # because no patient's phone is exactly "017".
    #
    # Equality, never LIKE. A pattern here would reopen the whole platform.
    reachable = belongs_to_clinic

    if q:
        matches_an_identifier_exactly = or_(
            # Emails are compared case-insensitively; nothing forces the
            # stored form to be lowercase.
            func.lower(User.email) == q.lower(),
            Patient.phone == q,
        )

        reachable = or_(belongs_to_clinic, matches_an_identifier_exactly)

    query = (
        select(Patient)
        .options(
            selectinload(Patient.user),
        )
        .join(
            User,
            Patient.user_id == User.id,
        )
        .where(reachable)
    )

    if q:
        pattern = f"%{q}%"

        # Kept as it was. An exact identifier also satisfies this, so the two
        # conditions never fight: the exception widens WHO is reachable, not
        # WHAT counts as a match.
        query = query.where(
            or_(
                User.full_name.ilike(pattern),
                User.email.ilike(pattern),
                Patient.phone.ilike(pattern),
            )
        )

    query = (
        query.order_by(User.full_name.asc())
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query)

    patients = result.scalars().all()

    return [
        PatientSearchOut(
            id=patient.id,
            user_id=patient.user_id,
            # users.full_name is nullable while PatientSearchOut.full_name is
            # a required str, so one nameless patient anywhere in the page
            # raised a ValidationError and took down the WHOLE response —
            # reception loses the search, not one row. Registration demands a
            # name so no live row is affected, but nothing at the database
            # level enforces that.
            full_name=patient.user.full_name or "",
            email=patient.user.email,
            phone=patient.phone,
        )
        for patient in patients
    ]

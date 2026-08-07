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
"""

from sqlalchemy import exists, or_, select
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

    query = (
        select(Patient)
        .options(
            selectinload(Patient.user),
        )
        .join(
            User,
            Patient.user_id == User.id,
        )
        .where(belongs_to_clinic)
    )

    q = q.strip()

    if q:
        pattern = f"%{q}%"

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
            full_name=patient.user.full_name,
            email=patient.user.email,
            phone=patient.phone,
        )
        for patient in patients
    ]

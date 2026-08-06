"""The soonest a patient can be seen, across a clinic's doctors.

"Who can see me today?" and "I need the earliest appointment" cannot be
answered from get_doctor_slots, which asks about one doctor at a time. Asking
it per doctor and picking the minimum would fan out across the whole roster and
still miss the point: the question is about the clinic.

CLINIC SCOPED, ALWAYS
---------------------
clinic_id is required rather than optional. HelpDoctor is multi-tenant and not
a marketplace: an assistant that surfaced a doctor from another clinic would be
a tenancy breach, and a default of "search everywhere" is exactly the kind of
default that becomes one by omission.

WHO CAN BE OFFERED
------------------
Approved doctors, with an active user account, at this clinic. A pending or
rejected doctor is not practising, and a deactivated account cannot be
consulted — offering either sends a patient to someone who will not see them.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_now
from app.domain.clinics.visibility import clinic_is_public
from app.models.clinic import Clinic
from app.models.doctor import Doctor, DoctorStatus
from app.models.doctor_slot import DoctorSlot
from app.models.user import User


async def find_earliest_available_doctor(
    db: AsyncSession,
    *,
    clinic_id: int,
    specialization: str | None = None,
    not_before: datetime | None = None,
    limit: int = 1,
) -> list[dict]:
    """The next free slots at this clinic, soonest first.

    `limit` exists so "who can see me today?" can offer a couple of options
    rather than a single take-it-or-leave-it time, and it stays small because
    this answers a question about the SOONEST appointment — a caller wanting a
    day's worth of times wants get_doctor_slots instead.

    Returns [] when nothing is free. That is a real answer, and the assistant
    is required to relay it as "I couldn't find any available doctor" rather
    than reaching for a nearby one.
    """
    # Slots strictly in the future. Without this the earliest match is whatever
    # sits lowest in the table, which for a clinic that has been running a
    # while is a slot from months ago.
    floor = not_before or utc_now()

    query = (
        select(
            DoctorSlot.id,
            DoctorSlot.start_time,
            DoctorSlot.end_time,
            Doctor.id.label("doctor_id"),
            Doctor.specialization,
            Doctor.consultation_fee,
            User.full_name,
        )
        .join(Doctor, DoctorSlot.doctor_id == Doctor.id)
        .join(User, Doctor.user_id == User.id)
        # Defence in depth: callers resolve the clinic through clinic_context,
        # which already applies this rule, but a service that can be called
        # with a bare id should not depend on every caller remembering.
        .join(Clinic, Doctor.clinic_id == Clinic.id)
        .where(
            Doctor.clinic_id == clinic_id,
            *clinic_is_public(),
            Doctor.status == DoctorStatus.APPROVED,
            User.is_active.is_(True),
            DoctorSlot.is_booked.is_(False),
            DoctorSlot.start_time > floor,
        )
        .order_by(DoctorSlot.start_time)
        .limit(limit)
    )

    if specialization:
        # Matched the way GET /doctors matches it, so "I need a cardiologist"
        # and a search for cardiologists cannot disagree about who counts as
        # one.
        query = query.where(
            Doctor.specialization.ilike(specialization.strip())
        )

    rows = (await db.execute(query)).all()

    return [
        {
            "slot_id": row.id,
            "doctor_id": row.doctor_id,
            "doctor_name": row.full_name,
            "specialization": row.specialization,
            "consultation_fee": (
                float(row.consultation_fee)
                if row.consultation_fee is not None
                else None
            ),
            # UTC, as stored. Presenting it in the clinic's local wall clock is
            # the formatting layer's job — this returns the fact.
            "start_time": row.start_time.isoformat(),
            "end_time": row.end_time.isoformat(),
        }
        for row in rows
    ]

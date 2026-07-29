"""Patient ratings of doctors.

The rules that matter here are trust rules, not CRUD:

* Only the patient who actually attended a COMPLETED appointment may rate it.
  Anything weaker turns the average into a brigading target.
* One rating per appointment, enforced in the database as well as here.
* Ratings stay editable for a short window, then freeze — so a patient can fix
  a mistake, but a doctor cannot pressure someone into rewriting history months
  later.
* Written comments never leave the clinic-admin surface.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment, AppointmentStatus
from app.models.doctor import Doctor
from app.models.doctor_rating import DoctorRating
from app.models.user import User, UserRole
from app.try_except.exceptions import (
    BadRequestError,
    ForbiddenError,
    NotFoundError,
)

logger = logging.getLogger(__name__)

EDIT_WINDOW_DAYS = 7


def is_editable(rating: DoctorRating) -> bool:
    created = rating.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - created <= timedelta(
        days=EDIT_WINDOW_DAYS
    )


async def _load_rateable_appointment(
    db: AsyncSession,
    user: User,
    appointment_id: int,
) -> Appointment:
    appointment = await db.scalar(
        select(Appointment).where(Appointment.id == appointment_id)
    )
    if appointment is None:
        raise NotFoundError("Appointment not found")

    # Note: appointments.patient_id references users.id.
    if user.role != UserRole.PATIENT or appointment.patient_id != user.id:
        # Deliberately the same error either way — do not let a caller probe
        # which appointment IDs exist for other patients.
        raise ForbiddenError("You can only rate your own appointments")

    if appointment.status != AppointmentStatus.COMPLETED:
        raise BadRequestError(
            "You can only rate an appointment after the consultation is complete"
        )

    return appointment


async def submit_rating(
    *,
    db: AsyncSession,
    user: User,
    appointment_id: int,
    stars: int,
    comment: str | None,
) -> DoctorRating:
    appointment = await _load_rateable_appointment(db, user, appointment_id)

    existing = await db.scalar(
        select(DoctorRating).where(
            DoctorRating.appointment_id == appointment_id
        )
    )

    if existing is not None:
        if not is_editable(existing):
            raise BadRequestError(
                f"This rating can no longer be changed "
                f"({EDIT_WINDOW_DAYS} days after it was submitted)"
            )
        existing.stars = stars
        existing.comment = comment
        await db.flush()
        await db.refresh(existing)
        return existing

    rating = DoctorRating(
        appointment_id=appointment.id,
        patient_id=user.id,
        doctor_id=appointment.doctor_id,
        clinic_id=appointment.clinic_id,
        stars=stars,
        comment=comment,
    )
    db.add(rating)
    await db.flush()
    await db.refresh(rating)
    return rating


async def get_my_rating(
    *,
    db: AsyncSession,
    user: User,
    appointment_id: int,
) -> DoctorRating | None:
    rating = await db.scalar(
        select(DoctorRating).where(
            DoctorRating.appointment_id == appointment_id,
            DoctorRating.patient_id == user.id,
        )
    )
    return rating


async def get_doctor_rating_summary(
    *,
    db: AsyncSession,
    doctor_id: int,
) -> dict:
    doctor = await db.scalar(select(Doctor).where(Doctor.id == doctor_id))
    if doctor is None:
        raise NotFoundError("Doctor not found")

    rows = await db.execute(
        select(DoctorRating.stars, func.count())
        .where(DoctorRating.doctor_id == doctor_id)
        .group_by(DoctorRating.stars)
    )

    distribution = {str(star): 0 for star in range(1, 6)}
    total = 0
    weighted = 0

    for stars, count in rows.all():
        distribution[str(stars)] = count
        total += count
        weighted += stars * count

    return {
        "doctor_id": doctor_id,
        "average": round(weighted / total, 2) if total else None,
        "count": total,
        "distribution": distribution,
    }


async def list_ratings_for_admin(
    *,
    db: AsyncSession,
    clinic_id: int,
    doctor_id: int,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Ratings including comments, scoped to the admin's own clinic."""

    result = await db.execute(
        select(DoctorRating, User.full_name)
        .join(User, DoctorRating.patient_id == User.id)
        .where(
            DoctorRating.doctor_id == doctor_id,
            DoctorRating.clinic_id == clinic_id,
        )
        .order_by(DoctorRating.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    return [
        {
            "id": rating.id,
            "appointment_id": rating.appointment_id,
            "doctor_id": rating.doctor_id,
            "stars": rating.stars,
            "comment": rating.comment,
            "patient_name": full_name,
            "created_at": rating.created_at,
        }
        for rating, full_name in result.all()
    ]

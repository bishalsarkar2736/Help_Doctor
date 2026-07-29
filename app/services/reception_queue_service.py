from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.doctor import Doctor

from app.schemas.reception_queue import (
    ReceptionQueueSummary,
    DoctorQueueSummary,
)

from app.services.waiting_queue_service import (
    get_doctor_queue_summary,
)


async def get_reception_queue_summary(
    *,
    db: AsyncSession,
    clinic_id: int,
) -> ReceptionQueueSummary:
    """
    Return queue information for every doctor
    in the specified clinic.
    """

    result = await db.execute(
        select(Doctor)
        .options(
            selectinload(Doctor.user),
        )
        .where(
            Doctor.clinic_id == clinic_id,
        )
        .order_by(Doctor.id)
    )

    doctors = result.scalars().all()

    doctor_queues: list[DoctorQueueSummary] = []

    for doctor in doctors:

        queue = await get_doctor_queue_summary(
            db=db,
            doctor_id=doctor.id,
        )

        doctor_queues.append(
            DoctorQueueSummary(
                doctor_id=doctor.id,
                doctor_name=doctor.user.full_name or "",
                current_patient=(
                    queue.current_patient.patient_name
                    if queue.current_patient
                    else None
                ),
                queue_length=queue.queue_length,
                average_wait_minutes=queue.average_wait_minutes,
            )
        )

    return ReceptionQueueSummary(
        doctors=doctor_queues,
    )
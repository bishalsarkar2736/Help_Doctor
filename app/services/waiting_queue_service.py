from sqlalchemy import select,func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import (
    Appointment,
    AppointmentStatus,
)
from app.core.constants import APPOINTMENT_DURATION_MINUTES as AVERAGE_CONSULTATION_MINUTES
from app.core.metrics import doctor_queue_length
from datetime import datetime

from app.core.time import UTC
from app.schemas.waiting_queue import (
    QueuePatient,
    WaitingQueueSummary,
    QueueStatsOut
)




async def get_next_waiting_patient(
    *,
    db: AsyncSession,
    doctor_id: int,
) -> Appointment | None:
    """
    Return the first patient currently waiting for this doctor.
    """

    waiting = await get_waiting_patients(
        db=db,
        doctor_id=doctor_id,
    )

    if not waiting:
        return None

    return waiting[0]




async def get_waiting_patients(
    *,
    db: AsyncSession,
    doctor_id: int,
) -> list[Appointment]:

    result = await db.execute(
        select(Appointment)
        .options(
            selectinload(Appointment.patient),
        )
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.status == AppointmentStatus.WAITING,
        )
        .order_by(Appointment.waiting_started_at.asc())
    )

    return result.scalars().all()



async def get_current_patient(
    *,
    db: AsyncSession,
    doctor_id: int,
) -> Appointment | None:
    """
    Return the patient currently being seen by the doctor.
    """
    
    result = await db.execute(
        select(Appointment)
        .options(
            selectinload(Appointment.patient),
        )
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.status == AppointmentStatus.IN_CONSULTATION,
        )
    )

    return result.scalar_one_or_none()


    


async def get_queue_length(
    *,
    db: AsyncSession,
    doctor_id: int,
) -> int:
    """
    Number of patients currently waiting for this doctor.
    """

    result = await db.scalar(
        select(func.count())
        .select_from(Appointment)
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.status == AppointmentStatus.WAITING,
        )
    )

    return result or 0



async def get_average_wait_time(
    *,
    db: AsyncSession,
    doctor_id: int,
) -> int:
    """
    Return the average waiting time (in minutes)
    for all patients currently in the waiting queue.
    """

    waiting_patients = await get_waiting_patients(
        db=db,
        doctor_id=doctor_id,
    )

    if not waiting_patients:
        return 0

    now = datetime.now(UTC)

    total_minutes = 0

    valid_count = 0

    for appointment in waiting_patients:

        if appointment.waiting_started_at is None:
            continue

        wait_minutes = (
            now - appointment.waiting_started_at
        ).total_seconds() / 60

        total_minutes += wait_minutes
        valid_count += 1

    if valid_count == 0:
        return 0

    return round(total_minutes / len(waiting_patients))


async def get_patient_position(
    *,
    db: AsyncSession,
    doctor_id: int,
    appointment_id: int,
) -> int | None:
    """
    Return the patient's position in the waiting queue.

    Returns:
        1,2,3,...
        None if the appointment is not waiting.
    """

    waiting_patients = await get_waiting_patients(
        db=db,
        doctor_id=doctor_id,
    )

    for index, appointment in enumerate(
        waiting_patients,
        start=1,
    ):
        if appointment.id == appointment_id:
            return index

    return None


async def estimate_wait_time(
    *,
    db: AsyncSession,
    doctor_id: int,
    appointment_id: int,
) -> int:
    """
    Estimate the remaining waiting time (in minutes)
    for a patient currently in the waiting queue.

    Position 1 -> 0 minutes
    Position 2 -> 20 minutes
    Position 3 -> 40 minutes
    ...
    """

    position = await get_patient_position(
        db=db,
        doctor_id=doctor_id,
        appointment_id=appointment_id,
    )

    if position is None:
        return 0

    return (position - 1) * AVERAGE_CONSULTATION_MINUTES



def estimate_wait_from_position(
    position: int | None,
) -> int:

    if position is None:
        return 0

    return (
        position - 1
    ) * AVERAGE_CONSULTATION_MINUTES



async def get_doctor_queue_summary(
    *,
    db: AsyncSession,
    doctor_id: int,
) -> WaitingQueueSummary:
    """
    Return the complete waiting queue for one doctor.
    """
  
    current = await get_current_patient(
        db=db,
        doctor_id=doctor_id,
    )

   
    waiting = await get_waiting_patients(
        db=db,
        doctor_id=doctor_id,
    )
  

    queue_length = await get_queue_length(
        db=db,
        doctor_id=doctor_id,
    )

    doctor_queue_length.labels(doctor_id=str(doctor_id)).set(queue_length)

    average_wait = await get_average_wait_time(
        db=db,
        doctor_id=doctor_id,
    )


    current_patient = None

    if current:
        current_patient = QueuePatient(
            appointment_id=current.id,
            patient_id=current.patient_id,
            patient_name=current.patient.full_name or "",
            scheduled_at=current.scheduled_at,
            waiting_started_at=current.waiting_started_at,
        )

    waiting_patients = [
        QueuePatient(
            appointment_id=appointment.id,
            patient_id=appointment.patient_id,
            patient_name=appointment.patient.full_name or "",
            scheduled_at=appointment.scheduled_at,
            waiting_started_at=appointment.waiting_started_at,
        )
        for appointment in waiting
    ]

    return WaitingQueueSummary(
        current_patient=current_patient,
        waiting=waiting_patients,
        queue_length=queue_length,
        average_wait_minutes=average_wait,
    )



async def get_queue_stats(
    *,
    db: AsyncSession,
    doctor_id: int,
) -> QueueStatsOut:
    """
    Return compact statistics for the doctor's live queue.
    """

    current = await get_current_patient(
        db=db,
        doctor_id=doctor_id,
    )

    waiting = await get_waiting_patients(
        db=db,
        doctor_id=doctor_id,
    )

    average_wait = await get_average_wait_time(
        db=db,
        doctor_id=doctor_id,
    )

    current_patient = None

    if current:
        current_patient = QueuePatient(
            appointment_id=current.id,
            patient_id=current.patient_id,
            patient_name=current.patient.full_name or "",
            scheduled_at=current.scheduled_at,
            waiting_started_at=current.waiting_started_at,
        )

    next_patient = None

    if waiting:
        first = waiting[0]

        next_patient = QueuePatient(
            appointment_id=first.id,
            patient_id=first.patient_id,
            patient_name=first.patient.full_name or "",
            scheduled_at=first.scheduled_at,
            waiting_started_at=first.waiting_started_at,
        )

    return QueueStatsOut(
        current_patient=current_patient,
        next_patient=next_patient,
        waiting_count=len(waiting),
        average_wait_minutes=average_wait,
    )
import pytest
from datetime import datetime

#from app.domain.fsm.appointment_transition import transition_appointment
from app.models.appointment import AppointmentStatus
from app.models.appointment_history import AppointmentStatusHistory
from sqlalchemy import select
from app.services.appointment_transition_service import transition_appointment_locked



# @pytest.mark.asyncio
# async def test_transition_creates_audit_entry(db, appointment, doctor_user):

#     await transition_appointment(
#         db=db,
#         appointment=appointment,
#         new_status=AppointmentStatus.CONFIRMED,
#         changed_by=doctor_user.id,
#     )

#     await db.flush()

#     result = await db.execute(
#         select(AppointmentStatusHistory).where(
#             AppointmentStatusHistory.appointment_id == appointment.id
#         )
#     )

#     history = result.scalars().all()

#     assert len(history) == 1
#     assert history[0].old_status == AppointmentStatus.PENDING
#     assert history[0].new_status == AppointmentStatus.CONFIRMED
#     assert history[0].changed_by == doctor_user.id


@pytest.mark.asyncio
async def test_transition_creates_audit_entry(db, appointment, doctor_user):

    await transition_appointment_locked(
        db=db,
        appointment=appointment,
        new_status=AppointmentStatus.CONFIRMED,
        changed_by=doctor_user.id,
        actor_role=doctor_user.role,
    )

    await db.flush()

    result = await db.execute(
        select(AppointmentStatusHistory).where(
            AppointmentStatusHistory.appointment_id == appointment.id
        )
    )

    history = result.scalars().all()

    assert len(history) == 1
    assert history[0].old_status == AppointmentStatus.PENDING
    assert history[0].new_status == AppointmentStatus.CONFIRMED
    assert history[0].changed_by == doctor_user.id
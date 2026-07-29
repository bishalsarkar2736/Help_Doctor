import pytest
from sqlalchemy import select

from app.models.appointment import AppointmentStatus
from app.models.notification import Notification
from app.services.appointment_service import admin_force_cancel_appointment
from app.models.doctor import Doctor
from app.workers.outbox_worker import process_outbox   # adjust import
from app.workers.outbox_worker import process_batch
from app.models.outbox_event import OutboxEvent

@pytest.mark.asyncio
async def test_admin_force_cancel(
    db,
    admin_user,
    appointment,
):
    # Act
    cancelled = await admin_force_cancel_appointment(
        db=db,
        admin=admin_user,   
        appointment_id=appointment.id,
        clinic_id=appointment.clinic_id,
        reason="Violation of policy",
    )

    await db.commit()

    # 🔍 DEBUG HERE (before processing outbox)
    result = await db.execute(select(OutboxEvent))
    events = result.scalars().all()

    print("EVENT COUNT:", len(events))
    for e in events:
        print("TYPE:", e.event_type)
        print("PAYLOAD:", e.payload)
        print("-----")



    await process_batch(db)

    # Assert appointment state
    assert cancelled.status == AppointmentStatus.CANCELLED
    assert cancelled.cancelled_at is not None
    assert cancelled.cancelled_by == admin_user.id
    assert cancelled.cancel_reason == "Violation of policy"

    # Assert notifications
    result = await db.execute(
        select(Notification).where(
            Notification.related_appointment_id == appointment.id
        )
    )
    notifications = result.scalars().all()

    assert len(notifications) == 2

    user_ids = {n.user_id for n in notifications}
    
    doctor = await db.get(Doctor, appointment.doctor_id)
    assert doctor.user_id in user_ids

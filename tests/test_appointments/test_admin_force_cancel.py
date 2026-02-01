import pytest
from sqlalchemy import select

from app.models.appointment import AppointmentStatus
from app.models.notification import Notification
from app.services.appointment_service import admin_force_cancel_appointment


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
        reason="Violation of policy",
    )

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
    assert appointment.patient_id in user_ids
    assert appointment.doctor_id in user_ids

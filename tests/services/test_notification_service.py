import pytest
from app.models.notification import Notification
from app.services.notification_service import mark_notification_as_read
from app.try_except.exceptions import BadRequestError

@pytest.mark.asyncio
async def test_user_can_mark_own_notification_as_read(db, patient_user):
    notification = Notification(
        user_id=patient_user.id,
        title="Test",
        message="Test message",
        read_at=None,
    )
    db.add(notification)
    await db.commit()
    await db.refresh(notification)

    updated = await mark_notification_as_read(
        db,
        patient_user,
        notification.id,
    )

    assert updated.read_at is not None




@pytest.mark.asyncio
async def test_user_cannot_mark_others_notification_as_read(
    db,
    patient_user,
    another_patient_user,
):
    notification = Notification(
        user_id=patient_user.id,
        title="Private",
        message="Private message",
        read_at=None,
    )
    db.add(notification)
    await db.commit()
    await db.refresh(notification)

    with pytest.raises(BadRequestError):
        await mark_notification_as_read(
            db,
            another_patient_user,
            notification.id,
        )


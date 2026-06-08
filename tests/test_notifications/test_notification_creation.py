# tests/test_notifications/test_notification_creation.py
import pytest
from app.services.notification_service import create_notification
import uuid


@pytest.mark.asyncio
async def test_notification_persisted(db, user,outbox_event):
    notification = await create_notification(
        db=db,
        user_id=user.id,
        title="Test",
        message="Hello",
        event_id=outbox_event.id,
    )

    assert notification.id is not None
    assert notification.user_id == user.id

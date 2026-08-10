
import pytest
from sqlalchemy import select

from app.models.notification import (
    Notification,
    NotificationCategory,
)
from app.models.outbox_event import OutboxEvent
from app.models.user import User, UserRole

from app.services.notification_receipt_service import (
    mark_email_delivered,
    mark_email_failed,
    mark_whatsapp_delivered,
    mark_whatsapp_failed,
    mark_push_delivered,
    mark_push_failed,
)


async def _create_notification(db):
    """
    Creates a notification attached to an OutboxEvent.
    Returns (notification, event)
    """

    user = User(
        email="patient@test.com",
        hashed_password="hash",
        role=UserRole.PATIENT,
    )
    db.add(user)
    await db.flush()

    event = OutboxEvent(
        event_type="PRESCRIPTION_ISSUED",
        payload={},
    )
    db.add(event)
    await db.flush()

    notification = Notification(
        user_id=user.id,
        title="Prescription",
        message="Issued",
        category=NotificationCategory.PRESCRIPTION,
        event_id=event.id,
    )

    db.add(notification)
    await db.commit()

    return notification, event


@pytest.mark.asyncio
async def test_mark_email_delivered(db):

    notification, event = await _create_notification(db)

    await mark_email_delivered(
        db=db,
        event_id=event.id,
        user_id=notification.user_id,
    )

    await db.commit()

    result = await db.execute(
        select(Notification).where(
            Notification.id == notification.id
        )
    )

    updated = result.scalar_one()

    assert updated.email_delivered_at is not None
    assert updated.delivered_at is not None


@pytest.mark.asyncio
async def test_mark_email_failed(db):

    notification, event = await _create_notification(db)

    await mark_email_failed(
        db=db,
        event_id=event.id,
        user_id=notification.user_id,
        error="SMTP timeout",
    )

    await db.commit()

    result = await db.execute(
        select(Notification).where(
            Notification.id == notification.id
        )
    )

    updated = result.scalar_one()

    assert updated.email_failed_at is not None
    assert updated.email_error == "SMTP timeout"


@pytest.mark.asyncio
async def test_mark_whatsapp_delivered(db):

    notification, event = await _create_notification(db)

    await mark_whatsapp_delivered(
        db=db,
        event_id=event.id,
        user_id=notification.user_id,
    )

    await db.commit()

    result = await db.execute(
        select(Notification).where(
            Notification.id == notification.id
        )
    )

    updated = result.scalar_one()

    assert updated.whatsapp_delivered_at is not None
    assert updated.delivered_at is not None


@pytest.mark.asyncio
async def test_mark_whatsapp_failed(db):

    notification, event = await _create_notification(db)

    await mark_whatsapp_failed(
        db=db,
        event_id=event.id,
        user_id=notification.user_id,
        error="Twilio unavailable",
    )

    await db.commit()

    result = await db.execute(
        select(Notification).where(
            Notification.id == notification.id
        )
    )

    updated = result.scalar_one()

    assert updated.whatsapp_failed_at is not None
    assert updated.whatsapp_error == "Twilio unavailable"


@pytest.mark.asyncio
async def test_mark_push_delivered(db):

    notification, event = await _create_notification(db)

    await mark_push_delivered(
        db=db,
        event_id=event.id,
        # A notification is identified by (event_id, user_id): one event can
        # carry a row for several recipients, so the receipt has to say which.
        user_id=notification.user_id,
    )

    await db.commit()

    result = await db.execute(
        select(Notification).where(
            Notification.id == notification.id
        )
    )

    updated = result.scalar_one()

    assert updated.push_delivered_at is not None
    assert updated.delivered_at is not None



@pytest.mark.asyncio
async def test_mark_push_failed(db):

    notification, event = await _create_notification(db)

    await mark_push_failed(
        db=db,
        event_id=event.id,
        user_id=notification.user_id,
        error="WebPush failed",
    )

    await db.commit()

    result = await db.execute(
        select(Notification).where(
            Notification.id == notification.id
        )
    )

    updated = result.scalar_one()

    assert updated.delivery_failed_at is not None
    assert updated.delivery_error == "WebPush failed"

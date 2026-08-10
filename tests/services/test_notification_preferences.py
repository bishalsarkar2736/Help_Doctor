import pytest
from unittest.mock import AsyncMock, patch

from app.models.notification_preference import (
    NotificationPreference,
)
import uuid
from app.models.notification import (
    NotificationCategory,
)
from app.websocket.manager import manager
from app.services.notification_service import (
    notify_user,
)
from app.models.outbox_event import OutboxEvent
from app.services.realtime_notification_service import (
    send_realtime_notification,
)

from app.services.notification_preference_service import (
    get_or_create_preferences,
    update_preferences,
)


@pytest.mark.asyncio
async def test_default_preferences_created(
    db,
    patient_user,
):
    prefs = await get_or_create_preferences(
        db,
        patient_user.id,
    )

    assert prefs.email_enabled is True
    assert prefs.push_enabled is True
    assert prefs.realtime_enabled is True

    # The odd one out, asserted alongside its siblings: WhatsApp is opt-in.
    assert prefs.whatsapp_enabled is False


@pytest.mark.asyncio
async def test_update_preferences(
    db,
    patient_user,
):
    prefs = await update_preferences(
        db=db,
        user_id=patient_user.id,
        email_enabled=False,
        push_enabled=False,
        realtime_enabled=False,
    )

    assert prefs.email_enabled is False
    assert prefs.push_enabled is False
    assert prefs.realtime_enabled is False


@pytest.mark.asyncio
async def test_push_disabled(
    db,
    patient_user,
    outbox_event,
):
    db.add(
        NotificationPreference(
            user_id=patient_user.id,
            push_enabled=False,
        )
    )

    await db.commit()

    with patch(
        "app.services.notification_service.send_push_notification_task.delay"
    ) as task:

        await notify_user(
            db=db,
            user_id=patient_user.id,
            title="Hello",
            message="World",
            category=NotificationCategory.SYSTEM,
            event_id=outbox_event.id,
        )

    task.assert_not_called()


@pytest.mark.asyncio
async def test_push_enabled(
    db,
    patient_user,
    outbox_event,
):
    db.add(
        NotificationPreference(
            user_id=patient_user.id,
            push_enabled=True,
        )
    )

    await db.commit()

    with patch(
        "app.services.notification_service.send_push_notification_task.delay"
    ) as task:

        await notify_user(
            db=db,
            user_id=patient_user.id,
            title="Hello",
            message="World",
            category=NotificationCategory.SYSTEM,
            event_id=outbox_event.id,
        )

    task.assert_called_once()


@pytest.mark.asyncio
async def test_realtime_disabled(
    db,
    patient_user,

):
    db.add(
        NotificationPreference(
            user_id=patient_user.id,
            realtime_enabled=False,
        )
    )

    await db.commit()

    with patch.object(
        manager,
        "notify_user",
        new=AsyncMock(),
    ) as mocked_notify:

        await send_realtime_notification(
            db=db,
            user_id=patient_user.id,
            payload={"hello": "world"},
        )

    mocked_notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_realtime_enabled(
    db,
    patient_user,
):
    db.add(
        NotificationPreference(
            user_id=patient_user.id,
            realtime_enabled=True,
        )
    )

    await db.commit()

    with patch.object(
        manager,
        "notify_user",
        new=AsyncMock(),
    ) as mocked_notify:
        

        await send_realtime_notification(
            db=db,
            user_id=patient_user.id,
            payload={"hello": "world"},
        )

    mocked_notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_existing_preferences(
    db,
    patient_user,
):
    db.add(
        NotificationPreference(
            user_id=patient_user.id,
            email_enabled=False,
            push_enabled=False,
            realtime_enabled=False,
        )
    )

    await db.commit()

    prefs = await get_or_create_preferences(
        db,
        patient_user.id,
    )

    assert prefs.email_enabled is False
    assert prefs.push_enabled is False
    assert prefs.realtime_enabled is False
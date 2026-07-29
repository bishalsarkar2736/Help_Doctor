"""Regression tests for the push-notification Celery task.

Guards the bug where the task called mark_push_delivered() /
mark_delivery_failed() without the required keyword-only `db` session, so every
push raised TypeError (and the except-branch raised the same TypeError, masking
the original error).
"""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.notification import Notification, NotificationCategory
from app.models.outbox_event import OutboxEvent
from app.task import notification_tasks


def _use_test_session(db):
    """Point the task's AsyncSessionLocal at the test session.

    conftest overrides FastAPI's get_db dependency, but not AsyncSessionLocal,
    so code that opens its own session would otherwise hit the dev database.
    Yields the test session without closing it.
    """

    @asynccontextmanager
    async def _cm():
        yield db

    return patch.object(notification_tasks, "AsyncSessionLocal", lambda: _cm())


# The task body, unwrapped from @celery_app.task and @run_async (asyncio.run).
_task_body = notification_tasks.send_push_notification_task.__wrapped__.__wrapped__


async def _notification(db, user_id: int) -> Notification:
    # notifications.event_id has an FK to outbox_events.id.
    event = OutboxEvent(
        event_type="NOTIFICATION_CREATED",
        payload={"user_id": user_id},
    )
    db.add(event)
    await db.flush()

    n = Notification(
        user_id=user_id,
        title="T",
        message="M",
        category=NotificationCategory.SYSTEM,
        event_id=event.id,
    )
    db.add(n)
    await db.commit()
    return n


@pytest.mark.asyncio
async def test_push_success_marks_delivered_and_commits(db, patient_user):
    n = await _notification(db, patient_user.id)

    with _use_test_session(db), patch.object(
        notification_tasks, "send_push_to_user", AsyncMock(return_value=None)
    ):
        await _task_body(
            None,
            user_id=patient_user.id,
            payload={"title": "T"},
            event_id=str(n.event_id),
        )

    refreshed = await db.scalar(
        select(Notification).where(Notification.event_id == n.event_id)
    )
    await db.refresh(refreshed)
    # Committed by the task — proves `db` was passed AND the commit landed.
    assert refreshed.push_delivered_at is not None
    assert refreshed.delivered_at is not None


@pytest.mark.asyncio
async def test_push_failure_records_delivery_error_and_reraises(db, patient_user):
    n = await _notification(db, patient_user.id)

    boom = RuntimeError("gateway down")

    with _use_test_session(db), patch.object(
        notification_tasks, "send_push_to_user", AsyncMock(side_effect=boom)
    ):
        with pytest.raises(RuntimeError, match="gateway down"):
            await _task_body(
                None,
                user_id=patient_user.id,
                payload={"title": "T"},
                event_id=str(n.event_id),
            )

    refreshed = await db.scalar(
        select(Notification).where(Notification.event_id == n.event_id)
    )
    await db.refresh(refreshed)
    # The failure was recorded (not swallowed by a second TypeError).
    assert refreshed.delivery_failed_at is not None
    assert "gateway down" in refreshed.delivery_error
    assert refreshed.push_delivered_at is None

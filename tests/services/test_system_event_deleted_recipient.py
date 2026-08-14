"""A system-initiated event must not write anything for a recipient who is gone.

WHERE THIS CAME FROM
96 dead-lettered events in this database are APPOINTMENT_STATUS_CHANGED with
source=SYSTEM, produced by mark_no_show_task. Every one names a patient_id, and
not one of those users still exists — the appointments and their patients were
deleted as test data long after the events were published.

WHAT HAPPENS TODAY
handle_notification_event skips notify_user for a SYSTEM event, because a cron
job's verdict is not a message from the clinic. But it then calls

    prefs = await get_or_create_preferences(db, user_id)

UNCONDITIONALLY, outside that guard. For a deleted user that inserts a
notification_preferences row pointing at a users id that is not there, which
violates notification_preferences_user_id_fkey and aborts the transaction.

The preferences are then used for exactly one decision — whether to send a
realtime notification — which is itself skipped for SYSTEM events. So the write
that breaks the event is made to answer a question that is never asked.

THE RULE
If nothing is being sent to the recipient, nothing should be created for them.
"""

import uuid

import pytest
from sqlalchemy import select

from app.models.appointment import AppointmentStatus
from app.models.notification import Notification
from app.models.notification_preference import NotificationPreference
from app.models.outbox_event import OutboxEvent
from app.schemas.event_metadata import EventSource
from app.schemas.event_registry import EVENT_SCHEMAS
from app.services.event_handlers.notification_handler import (
    handle_notification_event,
)

EVENT = "APPOINTMENT_STATUS_CHANGED"

#: Far outside anything the fixtures create.
DELETED_USER_ID = 9_999_001


def _system_event(*, patient_id: int, appointment_id: int):
    """The shape mark_no_show_task publishes."""
    return EVENT_SCHEMAS[EVENT](
        event_type=EVENT,
        schema_version=1,
        occurred_at="2026-08-14T00:00:00+00:00",
        aggregate_type="appointment",
        aggregate_id=appointment_id,
        source=EventSource.SYSTEM,
        patient_id=patient_id,
        appointment_id=appointment_id,
        doctor_id=1,
        new_status="NO_SHOW",
    )


@pytest.mark.asyncio
async def test_a_system_event_for_a_deleted_user_creates_no_preferences(db):
    """THE DEFECT. Currently this raises IntegrityError on
    notification_preferences_user_id_fkey and poisons the transaction."""

    before = await db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == DELETED_USER_ID
        )
    )
    assert before is None, "fixture assumption: this user does not exist"

    await handle_notification_event(
        db=db,
        validated=_system_event(
            patient_id=DELETED_USER_ID, appointment_id=9_999_002
        ),
        event_id=uuid.uuid4(),
        event_type=EVENT,
    )

    after = await db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == DELETED_USER_ID
        )
    )

    assert after is None, (
        "a preferences row was created for a user who does not exist, which "
        "violates notification_preferences_user_id_fkey"
    )


@pytest.mark.asyncio
async def test_the_transaction_is_still_usable_afterwards(db):
    """The FK violation aborted the transaction, which is what turned a
    harmless no-op into a dead-lettered event reporting the wrong cause."""

    await handle_notification_event(
        db=db,
        validated=_system_event(
            patient_id=DELETED_USER_ID, appointment_id=9_999_002
        ),
        event_id=uuid.uuid4(),
        event_type=EVENT,
    )

    # Any statement at all: a poisoned transaction refuses every one of them.
    assert await db.scalar(select(1)) == 1


@pytest.mark.asyncio
async def test_a_system_event_still_notifies_nobody(db):
    """Unchanged behaviour, stated so the fix cannot quietly start sending. A
    scheduled no-show is not a message from the clinic."""

    event_id = uuid.uuid4()

    await handle_notification_event(
        db=db,
        validated=_system_event(
            patient_id=DELETED_USER_ID, appointment_id=9_999_002
        ),
        event_id=event_id,
        event_type=EVENT,
    )

    sent = (
        await db.scalars(
            select(Notification).where(Notification.event_id == event_id)
        )
    ).all()

    assert sent == []


@pytest.mark.asyncio
async def test_a_system_event_for_a_LIVE_user_also_creates_no_preferences(
    db, patient_user, auth_doctor, appointment_factory
):
    """The guard is about what is being SENT, not about whether the user
    exists. A SYSTEM event contacts nobody, so it has no reason to create a
    preferences row for anybody — and this is the case that proves the fix is
    the guard rather than an existence check."""

    appointment = await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
    )

    existing = await db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == patient_user.id
        )
    )
    assert existing is None, "fixture assumption: no preferences row yet"

    await handle_notification_event(
        db=db,
        validated=_system_event(
            patient_id=patient_user.id, appointment_id=appointment.id
        ),
        event_id=uuid.uuid4(),
        event_type=EVENT,
    )

    after = await db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == patient_user.id
        )
    )

    assert after is None, (
        "a SYSTEM event created preferences even though it sends nothing"
    )


@pytest.mark.asyncio
async def test_a_user_initiated_event_is_untouched(
    db, patient_user, auth_doctor, appointment_factory
):
    """The paired allow-case: a real status change still notifies, and still
    resolves the recipient's preferences to decide on realtime delivery."""

    appointment = await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=auth_doctor["doctor"].id,
        status=AppointmentStatus.CONFIRMED,
    )

    # notifications.event_id is a foreign key into outbox_events: a real
    # notification needs a real event to hang off.
    event = OutboxEvent(event_type=EVENT, payload={})
    db.add(event)
    await db.flush()
    event_id = event.id

    validated = EVENT_SCHEMAS[EVENT](
        event_type=EVENT,
        schema_version=1,
        occurred_at="2026-08-14T00:00:00+00:00",
        aggregate_type="appointment",
        aggregate_id=appointment.id,
        patient_id=patient_user.id,
        appointment_id=appointment.id,
        doctor_id=auth_doctor["doctor"].id,
        new_status="CONFIRMED",
    )

    await handle_notification_event(
        db=db,
        validated=validated,
        event_id=event_id,
        event_type=EVENT,
    )

    sent = (
        await db.scalars(
            select(Notification).where(Notification.event_id == event_id)
        )
    ).all()

    assert len(sent) == 1, "a user-initiated status change must still notify"

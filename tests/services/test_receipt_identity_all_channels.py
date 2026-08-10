"""Every delivery receipt belongs to one recipient.

A notification is identified by (event_id, user_id) — that is what
uq_notification_event_user says, and it is what lets one event carry a
notification for several people.

Nine receipt helpers write outcomes onto those rows. Two were corrected
previously (mark_push_delivered, mark_delivery_failed); the remaining five
matched on event_id alone, so recording one recipient's outcome rewrote every
recipient's row. One patient's email arriving would have marked the doctor's
notification delivered, and one WhatsApp failure would have marked everyone
failed.

Latent rather than live, because the fan-out publishes a separate outbox row per
recipient, so one event_id currently maps to one notification. The constraint
permits otherwise and nothing enforces the present arrangement — which is
exactly the kind of assumption that stops being true quietly.

Every test here builds TWO notifications on ONE event, because that is the only
arrangement in which the bug is observable at all.
"""

import uuid

import pytest

from app.models.notification import Notification, NotificationCategory
from app.models.outbox_event import OutboxEvent
from app.models.user import User, UserRole
from app.services.notification_receipt_service import (
    mark_email_delivered,
    mark_email_failed,
    mark_notification_delivered,
    mark_notifications_seen,
    mark_push_failed,
    mark_whatsapp_delivered,
    mark_whatsapp_failed,
)


@pytest.fixture
async def shared_event(db):
    """One event, two notifications, two recipients."""
    users = []
    for tag in ("a", "b"):
        user = User(
            email=f"receipt-{tag}@example.com", full_name=f"User {tag.upper()}",
            hashed_password="x", role=UserRole.PATIENT, is_active=True,
        )
        db.add(user)
        users.append(user)

    await db.flush()

    event = OutboxEvent(
        id=uuid.uuid4(), event_type="PRESCRIPTION_ISSUED",
        payload={}, status="processed",
    )
    db.add(event)
    await db.flush()

    rows = []
    for user in users:
        notification = Notification(
            user_id=user.id, title="t", message="m",
            category=NotificationCategory.PRESCRIPTION, event_id=event.id,
        )
        db.add(notification)
        rows.append(notification)

    await db.flush()

    return {
        "event": event,
        "user_a": users[0], "user_b": users[1],
        "a": rows[0], "b": rows[1],
    }


async def _reload(db, notification):
    await db.refresh(notification)
    return notification


# Each channel: the helper, the column it writes, and whether it takes an error.
DELIVERED = [
    (mark_email_delivered, "email_delivered_at"),
    (mark_whatsapp_delivered, "whatsapp_delivered_at"),
]

FAILED = [
    (mark_email_failed, "email_failed_at", "email_error"),
    (mark_whatsapp_failed, "whatsapp_failed_at", "whatsapp_error"),
    (mark_push_failed, "delivery_failed_at", "delivery_error"),
]


# ---------------------------------------------------------------------------
# One recipient's success does not touch the other
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("mark, column", DELIVERED, ids=lambda v: getattr(v, "__name__", v))
async def test_success_marks_only_that_recipient(db, shared_event, mark, column):
    await mark(
        db=db,
        event_id=shared_event["event"].id,
        user_id=shared_event["user_a"].id,
    )

    a = await _reload(db, shared_event["a"])
    b = await _reload(db, shared_event["b"])

    assert getattr(a, column) is not None
    assert getattr(b, column) is None, (
        f"{mark.__name__} marked the other recipient's {column}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mark, column", DELIVERED, ids=lambda v: getattr(v, "__name__", v))
async def test_success_does_not_set_the_others_delivered_at(
    db, shared_event, mark, column
):
    """These helpers also write the aggregate delivered_at, so the leak had two
    columns, not one."""
    await mark(
        db=db,
        event_id=shared_event["event"].id,
        user_id=shared_event["user_a"].id,
    )

    assert (await _reload(db, shared_event["b"])).delivered_at is None


# ---------------------------------------------------------------------------
# One recipient's failure does not touch the other
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mark, column, error_column", FAILED, ids=lambda v: getattr(v, "__name__", v)
)
async def test_failure_marks_only_that_recipient(
    db, shared_event, mark, column, error_column
):
    await mark(
        db=db,
        event_id=shared_event["event"].id,
        user_id=shared_event["user_a"].id,
        error="channel unavailable",
    )

    a = await _reload(db, shared_event["a"])
    b = await _reload(db, shared_event["b"])

    assert getattr(a, column) is not None
    assert getattr(a, error_column) == "channel unavailable"

    assert getattr(b, column) is None, (
        f"{mark.__name__} marked the other recipient's {column}"
    )
    assert getattr(b, error_column) is None


@pytest.mark.asyncio
async def test_two_recipients_can_hold_opposite_outcomes(db, shared_event):
    """The state the old predicate could not represent: one channel landed for
    one person and failed for the other."""
    await mark_email_delivered(
        db=db, event_id=shared_event["event"].id,
        user_id=shared_event["user_a"].id,
    )
    await mark_email_failed(
        db=db, event_id=shared_event["event"].id,
        user_id=shared_event["user_b"].id, error="mailbox full",
    )

    a = await _reload(db, shared_event["a"])
    b = await _reload(db, shared_event["b"])

    assert a.email_delivered_at is not None and a.email_failed_at is None
    assert b.email_failed_at is not None and b.email_delivered_at is None


# ---------------------------------------------------------------------------
# Idempotent, and unchanged for a single recipient
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("mark, column", DELIVERED, ids=lambda v: getattr(v, "__name__", v))
async def test_repeating_success_keeps_the_first_timestamp(
    db, shared_event, mark, column
):
    """Write-once, so a redelivered task cannot drag the delivery time
    forward."""
    kwargs = dict(
        db=db,
        event_id=shared_event["event"].id,
        user_id=shared_event["user_a"].id,
    )

    await mark(**kwargs)
    first = getattr(await _reload(db, shared_event["a"]), column)

    await mark(**kwargs)

    assert getattr(await _reload(db, shared_event["a"]), column) == first


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mark, column, error_column", FAILED, ids=lambda v: getattr(v, "__name__", v)
)
async def test_repeating_failure_keeps_the_first_error(
    db, shared_event, mark, column, error_column
):
    """The first error explains the failure; later retries report symptoms."""
    kwargs = dict(
        db=db,
        event_id=shared_event["event"].id,
        user_id=shared_event["user_a"].id,
    )

    await mark(**kwargs, error="original cause")
    await mark(**kwargs, error="later symptom")

    assert getattr(
        await _reload(db, shared_event["a"]), error_column
    ) == "original cause"


@pytest.mark.asyncio
async def test_an_unknown_recipient_changes_nothing(db, shared_event):
    for mark, _ in DELIVERED:
        await mark(
            db=db, event_id=shared_event["event"].id, user_id=987654,
        )

    for mark, _, _ in FAILED:
        await mark(
            db=db, event_id=shared_event["event"].id, user_id=987654,
            error="x",
        )

    for row in ("a", "b"):
        stored = await _reload(db, shared_event[row])

        assert stored.delivered_at is None
        assert stored.email_delivered_at is None
        assert stored.email_failed_at is None
        assert stored.whatsapp_delivered_at is None
        assert stored.whatsapp_failed_at is None
        assert stored.delivery_failed_at is None


@pytest.mark.asyncio
async def test_a_single_recipient_event_is_unaffected(db):
    """The arrangement every event actually has today, which must not
    regress."""
    user = User(
        email="receipt-solo@example.com", full_name="Solo", hashed_password="x",
        role=UserRole.PATIENT, is_active=True,
    )
    db.add(user)
    await db.flush()

    event = OutboxEvent(
        id=uuid.uuid4(), event_type="PRESCRIPTION_ISSUED", payload={},
        status="processed",
    )
    db.add(event)
    await db.flush()

    notification = Notification(
        user_id=user.id, title="t", message="m",
        category=NotificationCategory.PRESCRIPTION, event_id=event.id,
    )
    db.add(notification)
    await db.flush()

    await mark_email_delivered(db=db, event_id=event.id, user_id=user.id)

    stored = await _reload(db, notification)

    assert stored.email_delivered_at is not None
    assert stored.delivered_at is not None


# ---------------------------------------------------------------------------
# The two that were already correct
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_notification_delivered_is_already_user_scoped(
    db, shared_event
):
    """Keyed on (notification_id, user_id) rather than the event — a different
    identity, and already the right one. Asserted so it stays that way."""
    await mark_notification_delivered(
        db=db,
        notification_id=shared_event["a"].id,
        user_id=shared_event["user_b"].id,
    )

    assert (await _reload(db, shared_event["a"])).delivered_at is None, (
        "another user marked this notification delivered"
    )


@pytest.mark.asyncio
async def test_mark_notifications_seen_is_already_user_scoped(db, shared_event):
    await mark_notifications_seen(
        notification_ids=[shared_event["a"].id],
        user_id=shared_event["user_b"].id,
        db=db,
    )

    assert (await _reload(db, shared_event["a"])).seen_at is None, (
        "another user marked this notification seen"
    )


# ---------------------------------------------------------------------------
# Every receipt helper is scoped — including any added later
# ---------------------------------------------------------------------------


def test_no_receipt_helper_matches_on_the_event_alone():
    """A guard on the shape, so a tenth helper cannot arrive carrying the
    defect all nine of these had."""
    import re
    from pathlib import Path

    source = (
        Path(__file__).parent.parent.parent
        / "app" / "services" / "notification_receipt_service.py"
    ).read_text()

    offenders = []

    for block in re.split(r"\nasync def ", source)[1:]:
        name = block.split("(")[0]

        if "update(Notification)" not in block:
            continue

        scoped = (
            "Notification.user_id == user_id" in block
            or "Notification.id == notification_id" in block
            or "Notification.id.in_(notification_ids)" in block
        )

        if not scoped:
            offenders.append(name)

    assert not offenders, (
        f"these receipt helpers write to notifications without identifying the "
        f"recipient: {offenders}"
    )

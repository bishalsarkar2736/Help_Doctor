"""Notification state means one thing, whichever channel or client got there.

Three semantics were incoherent.

delivered_at was written by four channels. Each guarded write-once on its OWN
column but overwrote the aggregate unconditionally, so email delivering at T1
then push at T2 left delivered_at = T2. The aggregate meant "the most recent
first-time channel delivery" — a value no reader could interpret. Realtime was
worse: it had no column of its own and guarded on the aggregate, so once any
other channel had delivered, a socket acknowledgement was discarded entirely.

seen_at could only be written through the WebSocket. A client without a live
socket could mark a notification READ but never SEEN.

And reading did not imply having seen, so a notification could be read and
never seen — which is not a state a user can actually be in.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.time import UTC, utc_now
from app.models.notification import Notification, NotificationCategory
from app.models.outbox_event import OutboxEvent
from app.models.user import User, UserRole
from app.security.jwt import create_access_token
from app.services.notification_center_service import (
    mark_all_notifications_read,
    mark_notification_read,
)
from app.services.notification_receipt_service import (
    mark_delivery_failed,
    mark_email_delivered,
    mark_notification_delivered,
    mark_notifications_seen,
    mark_push_delivered,
)


@pytest.fixture
async def two_recipients(db):
    """One event, two notifications, two users."""
    users = []
    for tag in ("a", "b"):
        user = User(
            email=f"state-{tag}@example.com", full_name=f"State {tag.upper()}",
            hashed_password="x", role=UserRole.PATIENT, is_active=True,
        )
        db.add(user)
        users.append(user)

    await db.flush()

    event = OutboxEvent(
        id=uuid.uuid4(), event_type="APPOINTMENT_CONFIRMED",
        payload={}, status="processed",
    )
    db.add(event)
    await db.flush()

    rows = []
    for user in users:
        notification = Notification(
            user_id=user.id, title="t", message="m",
            category=NotificationCategory.APPOINTMENT, event_id=event.id,
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


def _headers(user):
    token = create_access_token(
        data={"sub": str(user.id), "role": user.role.value}
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1. delivered_at is the FIRST delivery, whatever order channels arrive in
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_then_push_keeps_the_email_timestamp(db, two_recipients):
    """The exact regression: this used to end up as the push timestamp."""
    await mark_email_delivered(
        db=db, event_id=two_recipients["event"].id,
        user_id=two_recipients["user_a"].id,
    )

    first = (await _reload(db, two_recipients["a"])).email_delivered_at

    await mark_push_delivered(
        db=db, event_id=two_recipients["event"].id,
        user_id=two_recipients["user_a"].id,
    )

    stored = await _reload(db, two_recipients["a"])

    assert stored.delivered_at == first, (
        "a later channel moved the aggregate delivery time forward"
    )
    assert stored.push_delivered_at is not None
    assert stored.push_delivered_at != stored.delivered_at


@pytest.mark.asyncio
async def test_push_then_email_keeps_the_push_timestamp(db, two_recipients):
    """The same property in the other order, since a rule that only holds one
    way round is not a rule."""
    await mark_push_delivered(
        db=db, event_id=two_recipients["event"].id,
        user_id=two_recipients["user_a"].id,
    )

    first = (await _reload(db, two_recipients["a"])).push_delivered_at

    await mark_email_delivered(
        db=db, event_id=two_recipients["event"].id,
        user_id=two_recipients["user_a"].id,
    )

    stored = await _reload(db, two_recipients["a"])

    assert stored.delivered_at == first
    assert stored.email_delivered_at is not None


@pytest.mark.asyncio
async def test_realtime_first_sets_the_aggregate_and_its_own_column(
    db, two_recipients
):
    await mark_notification_delivered(
        db=db,
        notification_id=two_recipients["a"].id,
        user_id=two_recipients["user_a"].id,
    )

    stored = await _reload(db, two_recipients["a"])

    assert stored.realtime_delivered_at is not None
    assert stored.delivered_at == stored.realtime_delivered_at


@pytest.mark.asyncio
async def test_realtime_after_another_channel_is_still_recorded(
    db, two_recipients
):
    """The information that used to be thrown away.

    Realtime guarded on the aggregate, so once push had delivered, a socket
    acknowledgement set nothing at all and the fact was lost.
    """
    await mark_push_delivered(
        db=db, event_id=two_recipients["event"].id,
        user_id=two_recipients["user_a"].id,
    )

    first = (await _reload(db, two_recipients["a"])).delivered_at

    await mark_notification_delivered(
        db=db,
        notification_id=two_recipients["a"].id,
        user_id=two_recipients["user_a"].id,
    )

    stored = await _reload(db, two_recipients["a"])

    assert stored.realtime_delivered_at is not None, (
        "the realtime acknowledgement was discarded"
    )
    assert stored.delivered_at == first, "and it moved the aggregate"


@pytest.mark.asyncio
async def test_a_failure_alone_does_not_set_delivered_at(db, two_recipients):
    await mark_delivery_failed(
        db=db, event_id=two_recipients["event"].id,
        user_id=two_recipients["user_a"].id, error="unreachable",
    )

    stored = await _reload(db, two_recipients["a"])

    assert stored.delivery_failed_at is not None
    assert stored.delivered_at is None
    assert stored.push_delivered_at is None


@pytest.mark.asyncio
async def test_a_failure_then_a_success_keeps_both(db, two_recipients):
    await mark_delivery_failed(
        db=db, event_id=two_recipients["event"].id,
        user_id=two_recipients["user_a"].id, error="transient",
    )
    await mark_push_delivered(
        db=db, event_id=two_recipients["event"].id,
        user_id=two_recipients["user_a"].id,
    )

    stored = await _reload(db, two_recipients["a"])

    assert stored.delivery_failed_at is not None
    assert stored.delivery_error == "transient"
    assert stored.push_delivered_at is not None
    assert stored.delivered_at is not None


@pytest.mark.asyncio
async def test_repeating_a_receipt_does_not_move_the_first_timestamp(
    db, two_recipients
):
    kwargs = dict(
        db=db, event_id=two_recipients["event"].id,
        user_id=two_recipients["user_a"].id,
    )

    await mark_push_delivered(**kwargs)
    first = (await _reload(db, two_recipients["a"])).delivered_at

    await mark_push_delivered(**kwargs)

    assert (await _reload(db, two_recipients["a"])).delivered_at == first


@pytest.mark.asyncio
async def test_the_two_recipients_stay_isolated(db, two_recipients):
    """Delivery to one must not appear on the other, for the aggregate as well
    as the channel column."""
    await mark_email_delivered(
        db=db, event_id=two_recipients["event"].id,
        user_id=two_recipients["user_a"].id,
    )
    await mark_notification_delivered(
        db=db, notification_id=two_recipients["a"].id,
        user_id=two_recipients["user_a"].id,
    )

    other = await _reload(db, two_recipients["b"])

    assert other.delivered_at is None
    assert other.email_delivered_at is None
    assert other.realtime_delivered_at is None


# ---------------------------------------------------------------------------
# 2. REST mark-seen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_user_can_mark_their_notification_seen(
    client, db, two_recipients
):
    await db.commit()

    res = await client.patch(
        f"/notifications/{two_recipients['a'].id}/seen",
        headers=_headers(two_recipients["user_a"]),
    )

    assert res.status_code == 200, res.text
    assert (await _reload(db, two_recipients["a"])).seen_at is not None


@pytest.mark.asyncio
async def test_marking_seen_twice_is_idempotent(client, db, two_recipients):
    await db.commit()

    headers = _headers(two_recipients["user_a"])
    path = f"/notifications/{two_recipients['a'].id}/seen"

    await client.patch(path, headers=headers)
    first = (await _reload(db, two_recipients["a"])).seen_at

    res = await client.patch(path, headers=headers)

    assert res.status_code == 200, res.text
    assert (await _reload(db, two_recipients["a"])).seen_at == first, (
        "an existing seen_at was overwritten"
    )


@pytest.mark.asyncio
async def test_an_already_seen_notification_keeps_its_timestamp(
    client, db, two_recipients
):
    """A seen_at already recorded by the WebSocket is when the user actually saw
    it — earlier and more accurate than a later REST call."""
    earlier = utc_now() - timedelta(hours=2)
    two_recipients["a"].seen_at = earlier
    await db.commit()

    await client.patch(
        f"/notifications/{two_recipients['a'].id}/seen",
        headers=_headers(two_recipients["user_a"]),
    )

    assert (await _reload(db, two_recipients["a"])).seen_at == earlier


@pytest.mark.asyncio
async def test_another_users_notification_cannot_be_marked_seen(
    client, db, two_recipients
):
    await db.commit()

    res = await client.patch(
        f"/notifications/{two_recipients['b'].id}/seen",
        headers=_headers(two_recipients["user_a"]),
    )

    assert res.status_code == 403, res.text
    assert (await _reload(db, two_recipients["b"])).seen_at is None


@pytest.mark.asyncio
async def test_a_nonexistent_notification_is_not_found(client, db, two_recipients):
    await db.commit()

    res = await client.patch(
        "/notifications/987654/seen",
        headers=_headers(two_recipients["user_a"]),
    )

    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_marking_seen_requires_authentication(client, db, two_recipients):
    await db.commit()

    res = await client.patch(f"/notifications/{two_recipients['a'].id}/seen")

    assert res.status_code == 401, res.text
    assert (await _reload(db, two_recipients["a"])).seen_at is None


@pytest.mark.asyncio
async def test_a_notification_from_another_clinics_user_is_refused(
    client, db, two_recipients, default_clinic
):
    """No cross-clinic path is introduced: ownership is by user, and a user of
    another clinic is simply another user."""
    other_clinic_staff = User(
        email="state-otherclinic@example.com", full_name="Other Clinic Admin",
        hashed_password="x", role=UserRole.ADMIN, is_active=True,
        clinic_id=default_clinic.id,
    )
    db.add(other_clinic_staff)
    await db.flush()
    await db.commit()

    res = await client.patch(
        f"/notifications/{two_recipients['a'].id}/seen",
        headers=_headers(other_clinic_staff),
    )

    assert res.status_code == 403, res.text
    assert (await _reload(db, two_recipients["a"])).seen_at is None


@pytest.mark.asyncio
async def test_seen_does_not_imply_read(client, db, two_recipients):
    """The invariant is one-directional. Seeing something is not reading it."""
    await db.commit()

    await client.patch(
        f"/notifications/{two_recipients['a'].id}/seen",
        headers=_headers(two_recipients["user_a"]),
    )

    stored = await _reload(db, two_recipients["a"])

    assert stored.seen_at is not None
    assert stored.read_at is None


# ---------------------------------------------------------------------------
# 3. READ implies SEEN
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reading_an_unseen_notification_marks_it_seen(db, two_recipients):
    await mark_notification_read(
        db=db,
        user_id=two_recipients["user_a"].id,
        notification_id=two_recipients["a"].id,
    )

    stored = await _reload(db, two_recipients["a"])

    assert stored.read_at is not None
    assert stored.seen_at is not None, "read did not imply seen"


@pytest.mark.asyncio
async def test_reading_preserves_an_existing_seen_timestamp(db, two_recipients):
    earlier = utc_now() - timedelta(hours=3)
    two_recipients["a"].seen_at = earlier
    await db.flush()

    await mark_notification_read(
        db=db,
        user_id=two_recipients["user_a"].id,
        notification_id=two_recipients["a"].id,
    )

    assert (await _reload(db, two_recipients["a"])).seen_at == earlier


@pytest.mark.asyncio
async def test_mark_all_read_also_marks_unseen_as_seen(db, two_recipients):
    await mark_all_notifications_read(
        db=db, user_id=two_recipients["user_a"].id
    )

    stored = await _reload(db, two_recipients["a"])

    assert stored.read_at is not None
    assert stored.seen_at is not None


@pytest.mark.asyncio
async def test_mark_all_read_preserves_existing_seen(db, two_recipients):
    earlier = utc_now() - timedelta(hours=4)
    two_recipients["a"].seen_at = earlier
    await db.flush()

    await mark_all_notifications_read(
        db=db, user_id=two_recipients["user_a"].id
    )

    assert (await _reload(db, two_recipients["a"])).seen_at == earlier


@pytest.mark.asyncio
async def test_mark_all_read_leaves_other_users_alone(db, two_recipients):
    await mark_all_notifications_read(
        db=db, user_id=two_recipients["user_a"].id
    )

    other = await _reload(db, two_recipients["b"])

    assert other.read_at is None
    assert other.seen_at is None


@pytest.mark.asyncio
async def test_repeated_reads_are_idempotent(db, two_recipients):
    await mark_notification_read(
        db=db, user_id=two_recipients["user_a"].id,
        notification_id=two_recipients["a"].id,
    )

    first = await _reload(db, two_recipients["a"])
    read_at, seen_at = first.read_at, first.seen_at

    await mark_notification_read(
        db=db, user_id=two_recipients["user_a"].id,
        notification_id=two_recipients["a"].id,
    )
    await mark_all_notifications_read(
        db=db, user_id=two_recipients["user_a"].id
    )

    again = await _reload(db, two_recipients["a"])

    assert again.read_at == read_at
    assert again.seen_at == seen_at


@pytest.mark.asyncio
async def test_the_invariant_holds_across_every_row(db, two_recipients):
    """read implies seen, stated as the invariant rather than per-path."""
    await mark_all_notifications_read(
        db=db, user_id=two_recipients["user_a"].id
    )
    await mark_notification_read(
        db=db, user_id=two_recipients["user_b"].id,
        notification_id=two_recipients["b"].id,
    )

    violations = (
        await db.scalars(
            select(Notification.id).where(
                Notification.read_at.is_not(None),
                Notification.seen_at.is_(None),
            )
        )
    ).all()

    assert not violations, f"read but not seen: {violations}"


# ---------------------------------------------------------------------------
# 4. The unread badge is not stale after clearing everything
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_all_read_invalidates_the_unread_count(
    client, db, two_recipients
):
    """The regression: the count is cached, and mark-all did not invalidate it,
    so the badge kept its old value for the whole TTL after the user cleared
    their notifications."""
    await db.commit()

    headers = _headers(two_recipients["user_a"])

    before = await client.get("/notifications/unread/count", headers=headers)
    assert before.status_code == 200, before.text
    assert before.json()["count"] >= 1

    cleared = await client.patch("/notifications/read-all", headers=headers)
    assert cleared.status_code == 200, cleared.text

    after = await client.get("/notifications/unread/count", headers=headers)

    assert after.json()["count"] == 0, (
        "the unread count was served from a cache that mark-all did not clear"
    )

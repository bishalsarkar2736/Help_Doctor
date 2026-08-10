from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, update

from app.core.time import UTC

from app.models.notification import Notification
from app.core.metrics import (
    notification_sent_total,
    notification_failed_total,
)



async def mark_notification_delivered(
    *,
    db: AsyncSession,
    notification_id: int,
    user_id: int,
):


    now = datetime.now(UTC)

    await db.execute(
        update(Notification)
        .where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
            # Guarded on the REALTIME column, not the aggregate. Guarding on
            # delivered_at meant a socket acknowledgement was thrown away
            # whenever push or email had already delivered.
            Notification.realtime_delivered_at.is_(None),
        )
        .values(
            realtime_delivered_at=now,
            # First delivery wins. COALESCE keeps the earliest across all
            # channels without needing the aggregate in the WHERE clause,
            # which would otherwise block this channel from recording its own.
            delivered_at=func.coalesce(Notification.delivered_at, now),
        )
    )

    await db.commit()


async def mark_notifications_seen(
    *,
    db: AsyncSession,
    notification_ids: list[int],
    user_id: int,
):

    if not notification_ids:
        return

   

    await db.execute(
        update(Notification)
        .where(
            Notification.id.in_(notification_ids),
            Notification.user_id == user_id,
            Notification.seen_at.is_(None),
        )
        .values(
            seen_at=datetime.now(UTC)
        )
    )

    await db.commit()




async def mark_push_delivered(
    *,
    db: AsyncSession,
    event_id,
    user_id: int,
):
    """Record that THIS recipient's push arrived.

    user_id is part of the identity, not decoration. uq_notification_event_user
    is on (event_id, user_id), so one event can carry a notification for several
    people — and this matched on event_id alone, so delivering to one recipient
    marked every recipient's row delivered. One patient's phone receiving a push
    would have recorded the doctor's as delivered too.

    Only latent today, because the fan-out publishes a separate outbox row per
    recipient, so one event_id currently maps to one notification. The
    constraint allows otherwise and nothing enforces the current arrangement.

    WRITE-ONCE, so repeating the update is genuinely idempotent rather than
    merely harmless: the row keeps the FIRST delivery time instead of drifting
    forward on every redelivery, and the counter below only moves when
    something actually changed.
    """

    now = datetime.now(UTC)

    result = await db.execute(
        update(Notification)
        .where(
            Notification.event_id == event_id,
            Notification.user_id == user_id,
            Notification.push_delivered_at.is_(None),
        )
        .values(
            push_delivered_at=now,
            # First delivery wins: never overwritten by a later channel.
            delivered_at=func.coalesce(Notification.delivered_at, now),
        )
    )

    if result.rowcount:
        notification_sent_total.inc()



async def mark_push_failed(
    *,
    db: AsyncSession,
    event_id,
    user_id: int,
    error: str,
):
    """Record that THIS recipient's push failed.

    Not called by anything. The push task uses mark_delivery_failed; this is
    kept because proving a function unused is not the same as proving it
    unwanted, and removing it is a separate decision. Corrected alongside the
    others so it cannot be reintroduced carrying the old defect.
    """

    now = datetime.now(UTC)

    result = await db.execute(
        update(Notification)
        .where(
            Notification.event_id == event_id,
            Notification.user_id == user_id,
            Notification.delivery_failed_at.is_(None),
        )
        .values(
            delivery_failed_at=now,
            delivery_error=error[:1000],
        )
    )

    if result.rowcount:
        notification_failed_total.inc()



async def mark_email_delivered(
    *,
    db: AsyncSession,
    event_id,
    user_id: int,
):
    """Record that THIS recipient's email arrived.

    user_id is part of the identity: uq_notification_event_user is on
    (event_id, user_id), so matching on the event alone marked every recipient
    of it delivered — one patient's email would have recorded the doctor's
    notification as delivered too.
    """

    now = datetime.now(UTC)

    result = await db.execute(
        update(Notification)
        .where(
            Notification.event_id == event_id,
            Notification.user_id == user_id,
            Notification.email_delivered_at.is_(None),
        )
        .values(
            email_delivered_at=now,
            # First delivery wins: never overwritten by a later channel.
            delivered_at=func.coalesce(Notification.delivered_at, now),
        )
    )

    if result.rowcount:
        notification_sent_total.inc()


async def mark_email_failed(
    *,
    db: AsyncSession,
    event_id,
    user_id: int,
    error: str,
):
    """Record that THIS recipient's email failed.

    Write-once keeps the FIRST error, which is the one that explains the
    failure; later retries of an already-broken send report symptoms.
    """

    now = datetime.now(UTC)

    result = await db.execute(
        update(Notification)
        .where(
            Notification.event_id == event_id,
            Notification.user_id == user_id,
            Notification.email_failed_at.is_(None),
        )
        .values(
            email_failed_at=now,
            email_error=error[:1000],
        )
    )

    if result.rowcount:
        notification_failed_total.inc()


async def mark_delivery_failed(
    *,
    db: AsyncSession,
    event_id,
    user_id: int,
    error: str,
):
    """Record that THIS recipient's delivery failed.

    Same identity problem as mark_push_delivered: matching on event_id alone
    marked every recipient of the event as failed, including the ones whose
    push had gone out fine.

    Write-once for the same reason, and with one more: the FIRST error is the
    one that explains the failure. Later retries of an already-broken delivery
    tend to report downstream symptoms, and overwriting would lose the original
    cause. A subsequent success still sets push_delivered_at, so "failed, then
    recovered" stays legible.
    """

    now = datetime.now(UTC)

    result = await db.execute(
        update(Notification)
        .where(
            Notification.event_id == event_id,
            Notification.user_id == user_id,
            Notification.delivery_failed_at.is_(None),
        )
        .values(
            delivery_failed_at=now,
            delivery_error=error[:1000],
        )
    )

    if result.rowcount:
        notification_failed_total.inc()


async def mark_whatsapp_delivered(
    *,
    db: AsyncSession,
    event_id,
    user_id: int,
):
    """Record that THIS recipient's WhatsApp message arrived.

    Corrected for identity only. Nothing in the live pipeline calls this — the
    handler that would is wired nowhere — and this change does not wire it.
    """

    now = datetime.now(UTC)

    result = await db.execute(
        update(Notification)
        .where(
            Notification.event_id == event_id,
            Notification.user_id == user_id,
            Notification.whatsapp_delivered_at.is_(None),
        )
        .values(
            whatsapp_delivered_at=now,
            # First delivery wins: never overwritten by a later channel.
            delivered_at=func.coalesce(Notification.delivered_at, now),
        )
    )

    if result.rowcount:
        notification_sent_total.inc()


async def mark_whatsapp_failed(
    *,
    db: AsyncSession,
    event_id,
    user_id: int,
    error: str,
):
    """Record that THIS recipient's WhatsApp message failed."""

    now = datetime.now(UTC)

    result = await db.execute(
        update(Notification)
        .where(
            Notification.event_id == event_id,
            Notification.user_id == user_id,
            Notification.whatsapp_failed_at.is_(None),
        )
        .values(
            whatsapp_failed_at=now,
            whatsapp_error=error[:1000],
        )
    )

    if result.rowcount:
        notification_failed_total.inc()
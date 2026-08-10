"""The single publisher: every domain event becomes an outbox row here.

WHAT WAS REMOVED
This function opened with six print() calls and an unconditional
traceback.print_stack(limit=12) — a full stack dump, on stdout, for every event
the platform publishes. It was left-over debugging: which session am I in, which
connection, and who called this? Answers worth having once, at a keyboard.

It stopped being once-at-a-keyboard as the event system grew. Appointment,
payment, prescription and notification events all come through here, as do the
three reminder entry points, one of which is a scheduled job. So a stack trace
per publish, on stdout, bypassing the JSON formatter the API and workers were
given, and interleaved with every other process writing to the same stream.

The operational question behind it — which code path published this event? — is
answered properly by the structured record below: the event id, the type, and the
correlation id that ties the publish back to the request or job that caused it.

WHAT DELIBERATELY DID NOT CHANGE
No try/except was added. This function has never handled an exception: a failure
in flush() propagates to the caller, whose transaction owns the event and which
is where the failure is already recorded. Adding a handler here to log it would
either swallow the error or double-report it, and neither is an improvement.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox_event import OutboxEvent

logger = logging.getLogger(__name__)


async def publish_event(
    *,
    db: AsyncSession,
    event_type: str,
    payload: dict,
) -> OutboxEvent:

    event = OutboxEvent(
        event_type=event_type,
        payload=payload or {},  # ✅ safety
        correlation_id=payload.get("correlation_id"),
    )

    db.add(event)

    # ✅ ensure ID is generated immediately
    await db.flush()

    # ✅ structured logging (production useful)
    #
    # correlation_id is included because it is what the removed stack trace was
    # really for: it identifies the request or scheduled job this publish belongs
    # to, and does it in a field a log query can follow across the API, the
    # outbox worker and the notification handlers.
    logger.info(
        "outbox_event_created",
        extra={
            "event_id": str(event.id),
            "event_type": event_type,
            "correlation_id": event.correlation_id,
            "payload_keys": list(payload.keys()) if payload else [],
        },
    )

    return event

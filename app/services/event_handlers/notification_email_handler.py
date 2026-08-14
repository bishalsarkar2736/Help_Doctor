"""Email for the six events a patient should hear about out of band.

Email existed for exactly one event, PRESCRIPTION_ISSUED, through a dedicated
handler that attached the prescription PDF. That handler is gone: a prescription
document in an inbox is a disclosure this channel should not make, and the
product decision is that both prescription emails say only that a prescription
exists and point at the authenticated application. All six events now run
through this one path, so no two of them can drift apart on what they reveal.

WHAT SENDS EMAIL
Only EMAIL_EVENTS below. The allowlist is the mechanism, not a comment: an event
absent from it returns immediately, so adding a notification type does not
quietly start emailing patients.

WHO RECEIVES IT
Patients, and only patients.

That cannot be decided from the recipient's role, because three of these events
fan out to BOTH parties under one event type — booking, confirmation,
cancellation and reschedule each publish one event addressed to the patient and
one addressed to the doctor, with the same type and the same configuration. So
"is this the patient?" is answered from the aggregate:

    event → appointment_id → the appointment → appointment.patient_id

The appointment is the authoritative clinic context, so this also settles
tenancy without comparing clinic ids. Comparing them would be meaningless for a
patient anyway: patients are global identities and belong to every clinic that
has treated them. What matters is whether they are the patient OF THIS
APPOINTMENT, which a patient of another clinic cannot be.

RECIPIENT VALIDATION IS NOT REIMPLEMENTED HERE
handle_notification_event runs first in the composite and already refuses a
recipient who is not a party to the event, raising RecipientNotPartyToEvent —
which is non-retryable and preserves the event for dead-letter inspection.
Email is reached only after that has passed. The patient check below is a
narrowing of an already-validated recipient, not a second authorisation layer.

IDEMPOTENCY
Email is sent inline, so a redelivered outbox event re-runs this handler. The
guard is email_delivered_at, which the receipt helpers already maintain
write-once per (event_id, user_id): if it is set, this recipient has had their
email and there is nothing to do.

Deliberately NOT the Redis claim used for push. That guard exists because push
is ENQUEUED and the enqueue itself has no record; email writes its outcome to
the row it is about, so the row is the natural and cheaper answer. Two
mechanisms for one idea would be one too many.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment
from app.models.notification import Notification
from app.models.user import User
from app.services.email import send_email
from app.services.email_template_service import render_template
from app.services.notification_preference_service import (
    get_or_create_preferences,
)
from app.services.notification_receipt_service import (
    mark_email_delivered,
    mark_email_failed,
    record_delivery_failure,
)

logger = logging.getLogger(__name__)


def _refund_context(validated) -> dict:
    # refunded_amount is already in the in-app notification for this event, so
    # email carries nothing the patient cannot already see.
    return {"refunded_amount": getattr(validated, "refunded_amount", None)}


def _cancelled_context(validated) -> dict:
    # The ROLE, never the person: "your doctor" is what the patient needs, and
    # a name or an id is more than the in-app notification discloses.
    cancelled_by = getattr(validated, "cancelled_by", None) or {}

    role = (
        cancelled_by.get("role")
        if isinstance(cancelled_by, dict)
        else getattr(cancelled_by, "role", None)
    )

    return {"cancelled_by": (role or "the clinic").lower()}


# The allowlist. Six events, each with a static template and a fixed subject.
#
# No template renders a medicine, a diagnosis, a doctor's name or a database id.
# Appointment mail says the appointment changed and points at the app; the
# refund says how much; the prescription revision says a revision exists. That
# is the same information the in-app notification already carries, which is the
# ceiling this channel should have — an inbox is far less private than a
# logged-in session.
EMAIL_EVENTS: dict[str, dict] = {
    "APPOINTMENT_CONFIRMED": {
        "subject": "Your appointment is confirmed",
        "template": "emails/appointment_confirmed.html",
    },
    "APPOINTMENT_CANCELLED": {
        "subject": "Your appointment was cancelled",
        "template": "emails/appointment_cancelled.html",
        "context": _cancelled_context,
    },
    "APPOINTMENT_RESCHEDULED": {
        "subject": "Your appointment was rescheduled",
        "template": "emails/appointment_rescheduled.html",
    },
    "PAYMENT_REFUNDED": {
        "subject": "Your payment has been refunded",
        "template": "emails/payment_refunded.html",
        "context": _refund_context,
    },
    "PRESCRIPTION_REVISED": {
        "subject": "Your prescription has been revised",
        "template": "emails/prescription_revised.html",
    },
    # Served by this path too, since both prescription events now carry the
    # same safe content. It used to have a dedicated handler that attached the
    # prescription PDF — the whole document, in an inbox — which is exactly the
    # disclosure this channel is not the right place for. One implementation
    # means the two prescription emails cannot drift apart on what they reveal.
    "PRESCRIPTION_ISSUED": {
        "subject": "Your prescription has been issued",
        "template": "emails/prescription_issued.html",
    },
}


async def _already_emailed(
    db: AsyncSession, event_id, user_id: int
) -> bool:
    """Whether this recipient's email for this event has already gone.

    email_delivered_at is write-once per (event_id, user_id), so its presence is
    a complete answer for a redelivery.
    """
    return await db.scalar(
        select(Notification.email_delivered_at).where(
            Notification.event_id == event_id,
            Notification.user_id == user_id,
        )
    ) is not None


async def handle_notification_email(
    *,
    db: AsyncSession,
    validated,
    event_id,
    event_type: str,
    user_field: str,
) -> None:
    """Send the patient's email for one event, or decline to, with a reason."""

    config = EMAIL_EVENTS.get(event_type)

    if not config:
        return

    recipient_id = getattr(validated, user_field, None)
    appointment_id = getattr(validated, "appointment_id", None)

    if recipient_id is None or appointment_id is None:
        return

    appointment = await db.get(Appointment, appointment_id)

    if appointment is None:
        # Nothing to establish the clinic context from. Not an error worth
        # failing the event over — the in-app notification has already been
        # written and is the record that matters.
        logger.info(
            "notification_email_skipped",
            extra={
                "event_type": event_type,
                "reason": "appointment not found",
                "recipient_id": recipient_id,
            },
        )
        return

    # PATIENTS ONLY. The same event type also addresses the doctor, and this is
    # what tells the two apart — from the aggregate, not from a role column.
    if recipient_id != appointment.patient_id:
        return

    if await _already_emailed(db, event_id, recipient_id):
        logger.info(
            "notification_email_already_sent",
            extra={"event_type": event_type, "event_id": str(event_id)},
        )
        return

    patient = await db.get(User, recipient_id)

    if patient is None or not patient.email:
        return

    prefs = await get_or_create_preferences(db, recipient_id)

    if not prefs.email_enabled:
        logger.info(
            "notification_email_disabled",
            extra={"event_type": event_type, "user_id": recipient_id},
        )
        return

    context = config.get("context")

    html = render_template(
        config["template"],
        **(context(validated) if context else {}),
    )

    try:
        await send_email(
            to=patient.email,
            subject=config["subject"],
            body=config["subject"],
            html_body=html,
        )

        await mark_email_delivered(
            db=db, event_id=event_id, user_id=recipient_id
        )

        await db.commit()

    except Exception as exc:
        # Through the helper, not directly: when exc is a database error the
        # transaction is already aborted and this write would raise
        # PendingRollbackError from inside the except block, replacing exc.
        await record_delivery_failure(
            db,
            mark=mark_email_failed,
            event_id=event_id,
            user_id=recipient_id,
            error=str(exc),
        )

        logger.exception(
            "notification_email_failed",
            extra={
                "event_type": event_type,
                "event_id": str(event_id),
                "user_id": recipient_id,
            },
        )

        raise

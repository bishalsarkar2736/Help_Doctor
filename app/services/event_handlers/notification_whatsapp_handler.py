"""WhatsApp for the events approved for it, on the same rules as email.

Deliberately the same shape as notification_email_handler: one allowlist, the
patient identified from the event's aggregate, the channel preference respected,
the receipt written per (event_id, user_id), and idempotency taken from the
column the receipt already maintains. Two channels with two different notions of
"who is this for" is how they drift.

WHAT SENDS
The events in WHATSAPP_EVENTS below: a prescription being issued, the three
appointment changes a patient needs to know about out of band, and the two
payment outcomes. One table, one code path — an event is added by naming its
template setting and its parameters, never by writing another handler.

WHAT IS NOT HERE, AND WHY
The requested set also included APPOINTMENT_REMINDER, DOCTOR_RUNNING_LATE,
APPOINTMENT_COMPLETED, APPOINTMENT_NO_SHOW, PAYMENT_FAILED and PAYMENT_PENDING.
None of them is a domain event this platform publishes: none appears in
EVENT_SCHEMAS, and APPOINTMENT_REMINDER is published under the unregistered type
"appointment.reminder", which the outbox worker drops as unsupported. Adding them
here would be an allowlist entry that can never match a dispatched event, so the
channel would read as covering them while delivering nothing.

BODY PARAMETERS ARE POSITIONAL
Meta interpolates {{1}}, {{2}} by position, so each entry's parameter list must
match the order and count of its approved template. Getting it wrong is not a
validation error — it is a message with the time where the date should be.

TWO THINGS MUST BOTH BE TRUE BEFORE ANYTHING IS SENT
WHATSAPP_NOTIFICATIONS_ENABLED, and a configured template name for the event.

Meta only accepts business-initiated messages that reference a template approved
in Business Manager, so a missing name is not a configuration nicety — it is the
difference between a delivered message and a 400. The channel declines rather
than guessing, and says so in the log.

NO PRESCRIPTION DOCUMENT
The pre-existing prescription_whatsapp_handler uploads the prescription PDF and
sends it as a document. This does not, for the same reason the PDF was just
removed from email: the document is the whole prescription — medicines, dosages,
the lot — and WhatsApp is no more private than an inbox. The patient is told a
prescription exists and directed to the authenticated application.

That older handler is still unwired and is left untouched here; retiring it is a
content decision for WhatsApp that has not been taken yet.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.tz import to_zoneinfo
from app.models.appointment import Appointment
from app.models.clinic import Clinic
from app.models.doctor import Doctor
from app.models.notification import Notification
from app.models.patient import Patient
from app.models.user import User
from app.services.notification_preference_service import (
    get_or_create_preferences,
)
from app.services.notification_receipt_service import (
    mark_whatsapp_delivered,
    mark_whatsapp_failed,
)
from app.services.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)


async def _appointment_parameters(
    *, db, appointment, validated, timezone
) -> list[str]:
    """The appointment's date and time, as the patient's clinic reckons them.

    Positional and in this order, because Meta interpolates {{1}} and {{2}} by
    position: swapping them puts a time where the template says date.

    Converted into the clinic's timezone, never left in UTC. The platform's
    clinics run at UTC+6, so a 9am appointment stored as 03:00Z would be
    announced as "03:00 AM" — and for anything scheduled before 6am local the
    DATE would be wrong too, which is worse than a wrong hour because the
    patient has no way to notice it.
    """
    local = appointment.scheduled_at.astimezone(to_zoneinfo(timezone))

    return [
        local.strftime("%d %b %Y"),
        local.strftime("%I:%M %p"),
    ]


async def _refund_parameters(
    *, db, appointment, validated, timezone
) -> list[str]:
    """The refunded amount, which this event carries and no other does.

    Same currency convention as the in-app notification for the same event
    ("Your payment of ৳X has been refunded"), so the two do not disagree about
    what the patient was refunded.
    """
    return [f"৳{validated.refunded_amount}"]


def _doctor_label(full_name: str | None) -> str:
    """The doctor's name as a patient should read it.

    A name, never an id — the patient has no use for a doctor_id and it is
    internal. Prefixed with "Dr." unless the stored name already carries a title,
    because names in this table are entered by hand and some already do; blindly
    prefixing produces "Dr. Dr. Rahman".
    """
    name = (full_name or "").strip()

    if not name:
        # No name is better than a wrong one, and better than an id. The template
        # still renders; the doctor slot reads as unspecified.
        return "your doctor"

    lowered = name.lower()

    if lowered.startswith("dr.") or lowered.startswith("dr "):
        return name

    return f"Dr. {name}"


async def _reminder_parameters(
    *, db, appointment, validated, timezone
) -> list[str]:
    """Doctor, date and time — in that order, and nothing else.

    Three parameters because the approved reminder template names the doctor,
    which the other appointment templates do not. The name is resolved from the
    appointment's doctor rather than carried in the event, so a doctor who
    changes their name is announced correctly by a reminder queued yesterday.

    The date is "12 August" and the time "10:30 AM", both in the clinic's own
    timezone. No year: the reminder is for an appointment within a day, so a year
    is noise, and this is the format the approved template was written around.
    """
    full_name = await db.scalar(
        select(User.full_name)
        .join(Doctor, Doctor.user_id == User.id)
        .where(Doctor.id == appointment.doctor_id)
    )

    local = appointment.scheduled_at.astimezone(to_zoneinfo(timezone))

    return [
        _doctor_label(full_name),
        local.strftime("%d %B"),
        local.strftime("%I:%M %p"),
    ]


# Sends the approved template with no body parameters. The template's own text
# is the entire message, so nothing from the event reaches the reader.
_PARAMETERLESS = None


# The allowlist, and the only place an event becomes a WhatsApp event. An event
# absent from here sends nothing, so adding a notification type cannot quietly
# start messaging patients.
#
# Every entry names a settings attribute holding a Meta-approved template name,
# and either a parameter builder or _PARAMETERLESS. The parameter list is part of
# the allowlist rather than derived, because the count and order have to match
# what Meta approved for that template.
#
# ONLY EVENTS THE PLATFORM ACTUALLY PUBLISHES ARE HERE. An entry for an event
# with no schema in EVENT_SCHEMAS and no publisher would be unreachable code that
# reads as a delivered feature.
WHATSAPP_EVENTS: dict[str, dict] = {
    # Unchanged. Says a prescription exists and nothing about its contents; the
    # document itself is deliberately not sent on this channel.
    "PRESCRIPTION_ISSUED": {
        "template_setting": "WHATSAPP_TEMPLATE_PRESCRIPTION_ISSUED",
        "parameters": _PARAMETERLESS,
    },

    "APPOINTMENT_CONFIRMED": {
        "template_setting": "WHATSAPP_TEMPLATE_APPOINTMENT_CONFIRMED",
        "parameters": _appointment_parameters,
    },

    "APPOINTMENT_CANCELLED": {
        "template_setting": "WHATSAPP_TEMPLATE_APPOINTMENT_CANCELLED",
        # Date and time only. The event also carries cancelled_by and a free-text
        # reason; neither is sent. The reason is typed by staff and so is
        # unbounded text that could name a condition, and WhatsApp is the least
        # private channel the platform has.
        "parameters": _appointment_parameters,
    },

    "APPOINTMENT_RESCHEDULED": {
        "template_setting": "WHATSAPP_TEMPLATE_APPOINTMENT_RESCHEDULED",
        # The NEW date and time: the appointment row has already been moved by
        # the time this event is dispatched, so scheduled_at is the new slot.
        "parameters": _appointment_parameters,
    },

    # Published by a scheduled job, unlike every other event here. That makes no
    # difference to this handler: the event carries source=USER, is dispatched
    # through the same route, and is subject to the same gates.
    "APPOINTMENT_REMINDER": {
        "template_setting": "WHATSAPP_TEMPLATE_APPOINTMENT_REMINDER",
        "parameters": _reminder_parameters,
    },

    "PAYMENT_SUCCESS": {
        "template_setting": "WHATSAPP_TEMPLATE_PAYMENT_SUCCESS",
        # No amount. PaymentSuccessEvent carries user_id and appointment_id and
        # nothing else — there is no amount in the event to map, and reading one
        # off the Payment table would be this channel inventing a field the event
        # does not have. The approved template must therefore say that a payment
        # was received without stating how much.
        "parameters": _PARAMETERLESS,
    },

    "PAYMENT_REFUNDED": {
        "template_setting": "WHATSAPP_TEMPLATE_PAYMENT_REFUNDED",
        "parameters": _refund_parameters,
    },
}


async def _already_sent(db: AsyncSession, event_id, user_id: int) -> bool:
    """Whether this recipient's WhatsApp message for this event has gone.

    whatsapp_delivered_at is write-once per (event_id, user_id), so its presence
    is a complete answer for a redelivery — the same guard email uses, and for
    the same reason: the outcome is recorded on the row it is about, so no
    separate claim is needed.
    """
    return await db.scalar(
        select(Notification.whatsapp_delivered_at).where(
            Notification.event_id == event_id,
            Notification.user_id == user_id,
        )
    ) is not None


async def handle_notification_whatsapp(
    *,
    db: AsyncSession,
    validated,
    event_id,
    event_type: str,
    user_field: str,
) -> None:
    """Send the patient's WhatsApp message for one event, or decline to."""

    config = WHATSAPP_EVENTS.get(event_type)

    if not config:
        return

    settings = get_settings()

    if not settings.WHATSAPP_NOTIFICATIONS_ENABLED:
        return

    template_attr = config["template_setting"]
    template_name = getattr(settings, template_attr, "")

    if not template_name:
        # Approved templates live in Meta Business Manager, not here. Without a
        # name there is nothing valid to send, and guessing one would be a 400.
        logger.warning(
            "whatsapp_template_not_configured",
            extra={"event_type": event_type, "setting": template_attr},
        )
        return

    recipient_id = getattr(validated, user_field, None)
    appointment_id = getattr(validated, "appointment_id", None)

    if recipient_id is None or appointment_id is None:
        return

    appointment = await db.get(Appointment, appointment_id)

    if appointment is None:
        logger.info(
            "whatsapp_skipped",
            extra={
                "event_type": event_type,
                "reason": "appointment not found",
                "recipient_id": recipient_id,
            },
        )
        return

    # PATIENTS ONLY, decided from the aggregate rather than from a role: the
    # appointment is the authoritative clinic context, and its patient is the
    # only person this channel writes to. A patient of another clinic cannot be
    # the patient of THIS appointment, while the same global patient can be at
    # two clinics at once.
    if recipient_id != appointment.patient_id:
        return

    if await _already_sent(db, event_id, recipient_id):
        logger.info(
            "whatsapp_already_sent",
            extra={"event_type": event_type, "event_id": str(event_id)},
        )
        return

    phone = await db.scalar(
        select(Patient.phone).where(Patient.user_id == recipient_id)
    )

    if not phone:
        logger.info(
            "whatsapp_skipped",
            extra={"event_type": event_type, "reason": "no phone on file"},
        )
        return

    prefs = await get_or_create_preferences(db, recipient_id)

    if not prefs.whatsapp_enabled:
        logger.info(
            "whatsapp_disabled",
            extra={"event_type": event_type, "user_id": recipient_id},
        )
        return

    builder = config["parameters"]

    body_parameters = None

    if builder is not None:
        # The clinic's timezone, read from the appointment's own clinic — so the
        # date and time are the ones the patient was given, not the server's.
        timezone = await db.scalar(
            select(Clinic.timezone).where(Clinic.id == appointment.clinic_id)
        )

        body_parameters = await builder(
            db=db,
            appointment=appointment,
            validated=validated,
            timezone=timezone,
        )

    try:
        # Only the parameters the event's own builder produced: a date, a time or
        # an amount. No diagnosis, medicine, dosage, clinical note, doctor name or
        # database id reaches a parameter, so the approved template's text is the
        # entire clinical content of the message — which is none.
        await WhatsAppService.send_template(
            phone=phone,
            template_name=template_name,
            language=settings.WHATSAPP_TEMPLATE_LANGUAGE,
            body_parameters=body_parameters,
        )

        await mark_whatsapp_delivered(
            db=db, event_id=event_id, user_id=recipient_id
        )

        await db.commit()

    except Exception as exc:
        await mark_whatsapp_failed(
            db=db, event_id=event_id, user_id=recipient_id, error=str(exc)
        )

        await db.commit()

        logger.exception(
            "whatsapp_send_failed",
            extra={
                "event_type": event_type,
                "event_id": str(event_id),
                "user_id": recipient_id,
            },
        )

        # Re-raised so the outbox retries it like any other delivery failure.
        raise

"""PAYMENT_FAILED: the domain event, and the publisher that emits it.

WHAT HAD TO EXIST FIRST
PAYMENT_FAILED was not a domain event. The WhatsApp handler's docstring listed it
among events this platform publishes nothing for, and warned that an allowlist
entry for one "would be an allowlist entry that can never match a dispatched
event, so the channel would read as covering them while delivering nothing."

So the chain was built in dependency order, and this file asserts the links that
sit BELOW the channel:

    PaymentFailedEvent                schema
    EVENT_SCHEMAS["PAYMENT_FAILED"]   registry -- the outbox worker drops
                                      unregistered types as unsupported
    mark_payment_failed               publisher
    EVENT_HANDLERS["PAYMENT_FAILED"]  dispatcher route
    EVENT_NOTIFICATION_CONFIG         without it _with_patient_channels returns
                                      BEFORE reaching any channel, and there is
                                      no Notification row for the receipt
    WHATSAPP_EVENTS                   the allowlist entry, added last

The channel's own behaviour -- sending, preferences, idempotency, logging -- is
tested in test_notification_whatsapp_channel.py, alongside every other event on
that channel and using its fixtures.

WHY THE PUBLISHER IS IN mark_payment_failed
Two callers reach it: the bKash webhook (_handle_failed_bkash_payment) and the
scheduled reconciliation job. Publishing at either call site alone would leave a
payment that failed the other way notifying nobody, and the patient cannot tell
which route marked theirs.
"""

import uuid

import pytest
from sqlalchemy import select

from app.models.appointment import AppointmentStatus
from app.models.enums.payment_status import PaymentStatus
from app.models.outbox_event import OutboxEvent
from app.models.payment import Payment
from app.schemas.event_registry import EVENT_SCHEMAS
from app.services.event_handlers.dispatcher import EVENT_HANDLERS
from app.services.event_handlers.notification_handler import (
    EVENT_NOTIFICATION_CONFIG,
)
from app.services.event_handlers.notification_whatsapp_handler import (
    WHATSAPP_EVENTS,
    _PARAMETERLESS,
)
from app.services.payment_service import mark_payment_failed

EVENT = "PAYMENT_FAILED"


# ---------------------------------------------------------------------------
# The chain exists, in dependency order
# ---------------------------------------------------------------------------


def test_the_event_has_a_registered_schema():
    """Without registration the outbox worker drops the event as an unsupported
    type -- the failure mode APPOINTMENT_REMINDER shipped with for weeks."""
    assert EVENT in EVENT_SCHEMAS

    fields = EVENT_SCHEMAS[EVENT].model_fields

    assert "user_id" in fields
    assert "appointment_id" in fields


def test_the_event_carries_no_amount_and_no_reason():
    """THE CONTENT DECISION, pinned. Either would flow to a patient-facing
    channel that is no more private than an inbox."""
    fields = set(EVENT_SCHEMAS[EVENT].model_fields)

    for forbidden in ("amount", "reason", "failure_reason", "refunded_amount"):
        assert forbidden not in fields, (
            f"PaymentFailedEvent carries {forbidden!r}, which would reach WhatsApp"
        )


def test_it_is_routed_through_the_patient_channels():
    from app.services.event_handlers.dispatcher import _with_patient_channels

    assert EVENT_HANDLERS.get(EVENT) is _with_patient_channels


def test_the_notification_config_entry_exists():
    """Not decoration: _with_patient_channels reads this map and returns early
    when an event is missing, so WhatsApp would never be reached -- and the
    Notification row it creates is the row the WhatsApp receipt is written on."""
    assert EVENT in EVENT_NOTIFICATION_CONFIG

    config = EVENT_NOTIFICATION_CONFIG[EVENT]

    assert config["user_field"] == "user_id"
    assert config["appointment_field"] == "appointment_id"


def test_the_in_app_message_states_no_amount_or_reason():
    config = EVENT_NOTIFICATION_CONFIG[EVENT]

    text = config.get("message", "") + config.get("message_template", "")

    assert text, "the notification has no message"
    assert "{" not in text, "a placeholder would interpolate event data"

    for forbidden in ("৳", "amount", "reason"):
        assert forbidden not in text.lower()


# ---------------------------------------------------------------------------
# The template is its own, and parameterless
# ---------------------------------------------------------------------------


def test_it_names_its_own_template_setting():
    assert EVENT in WHATSAPP_EVENTS
    assert WHATSAPP_EVENTS[EVENT]["template_setting"] == (
        "WHATSAPP_TEMPLATE_PAYMENT_FAILED"
    )


def test_the_template_setting_defaults_to_unconfigured():
    """Empty means "not approved in Business Manager yet", and the channel
    declines rather than guessing a name Meta would reject with a 400."""
    from app.config import Settings

    assert Settings.model_fields["WHATSAPP_TEMPLATE_PAYMENT_FAILED"].default == ""


def test_no_two_events_share_a_template_setting():
    """Meta approves each template separately, and a failure message is not a
    success message. This is what a per-event setting is for."""
    used = [config["template_setting"] for config in WHATSAPP_EVENTS.values()]

    assert len(used) == len(set(used))


def test_it_sends_no_body_parameters():
    """Parameterless, like PAYMENT_SUCCESS: there is nothing on the event to fill
    a {{1}} placeholder with, so the approved template must not contain one."""
    assert WHATSAPP_EVENTS[EVENT]["parameters"] is _PARAMETERLESS


# ---------------------------------------------------------------------------
# The publisher
# ---------------------------------------------------------------------------


@pytest.fixture
async def pending_payment(db, patient_user, doctor, appointment_factory):
    appointment = await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        status=AppointmentStatus.CONFIRMED,
    )

    payment = Payment(
        appointment_id=appointment.id,
        patient_id=patient_user.id,
        clinic_id=appointment.clinic_id,
        method="bkash",
        amount=500,
        status=PaymentStatus.PENDING,
        public_invoice_id=f"INV-{uuid.uuid4().hex[:12].upper()}",
        gateway_payment_id=f"GW-{uuid.uuid4().hex[:10]}",
    )

    db.add(payment)
    await db.flush()

    return payment


async def _published(db) -> list[OutboxEvent]:
    return list(
        await db.scalars(select(OutboxEvent).where(OutboxEvent.event_type == EVENT))
    )


@pytest.mark.asyncio
async def test_marking_a_payment_failed_publishes_the_event(db, pending_payment):
    """Published from mark_payment_failed so BOTH callers -- the bKash webhook
    and the reconciliation job -- produce it."""
    await mark_payment_failed(
        db=db,
        gateway_payment_id=pending_payment.gateway_payment_id,
        reason="declined",
    )

    events = await _published(db)

    assert len(events) == 1
    assert events[0].payload["user_id"] == pending_payment.patient_id
    assert events[0].payload["appointment_id"] == pending_payment.appointment_id


@pytest.mark.asyncio
async def test_the_published_event_carries_no_reason_or_amount(db, pending_payment):
    """The publisher receives `reason` as an argument. It must stay in
    payment_metadata and out of the event -- it is unbounded gateway text."""
    await mark_payment_failed(
        db=db,
        gateway_payment_id=pending_payment.gateway_payment_id,
        reason="insufficient funds on card ending 4242",
    )

    event = (await _published(db))[0]

    rendered = str(event.payload)

    assert "insufficient funds" not in rendered
    assert "4242" not in rendered
    assert "amount" not in event.payload
    assert "reason" not in event.payload


@pytest.mark.asyncio
async def test_the_reason_is_still_recorded_on_the_payment(db, pending_payment):
    """Dropped from the event, NOT lost: staff need it, and payment_metadata is
    where the application already shows it."""
    await mark_payment_failed(
        db=db,
        gateway_payment_id=pending_payment.gateway_payment_id,
        reason="insufficient funds",
    )

    assert pending_payment.payment_metadata["failure_reason"] == "insufficient funds"


@pytest.mark.asyncio
async def test_a_redelivered_webhook_publishes_only_once(db, pending_payment):
    """mark_payment_failed returns early once the payment is no longer PENDING,
    so the second call publishes nothing. The duplicate is never created, rather
    than being de-duplicated downstream."""
    for _ in range(2):
        await mark_payment_failed(
            db=db,
            gateway_payment_id=pending_payment.gateway_payment_id,
            reason="declined",
        )

    assert len(await _published(db)) == 1


@pytest.mark.asyncio
async def test_a_successful_payment_is_neither_failed_nor_published(db, pending_payment):
    """The PENDING guard is pre-existing behaviour and must stay untouched: a
    late failure webhook for an already-successful payment changes nothing."""
    pending_payment.status = PaymentStatus.SUCCESS
    await db.flush()

    result = await mark_payment_failed(
        db=db,
        gateway_payment_id=pending_payment.gateway_payment_id,
        reason="declined",
    )

    assert result.status == PaymentStatus.SUCCESS
    assert await _published(db) == []


@pytest.mark.asyncio
async def test_the_status_change_and_the_event_are_one_transaction(db, pending_payment):
    """The publish joins the caller's transaction rather than committing. A
    payment quietly marked failed with nobody told is the outcome to avoid, so
    the row and its outbox event are written together or not at all."""
    await mark_payment_failed(
        db=db,
        gateway_payment_id=pending_payment.gateway_payment_id,
        reason="declined",
    )

    assert pending_payment.status == PaymentStatus.FAILED
    assert len(await _published(db)) == 1

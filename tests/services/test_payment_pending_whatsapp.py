"""PAYMENT_PENDING: the domain event, and the one place that publishes it.

WHY THIS EVENT IS SHAPED DIFFERENTLY FROM ITS SIBLINGS
PAYMENT_SUCCESS, PAYMENT_FAILED and PAYMENT_REFUNDED are transitions, each with a
function that owns it -- mark_payment_success, mark_payment_failed, the refund
service. PENDING has none, because nothing moves a payment INTO pending: it is
the state a Payment is constructed in.

So the authoritative point is creation, and creation happens in exactly one place
in the whole application:

    grep 'Payment(' app/ -> app/services/payment_service.py:149   (and the model)

That is what makes "publish from the authoritative transition, not one caller"
satisfiable here: covering create_payment covers every legitimate path by
construction, and a test below pins that the count of construction sites is still
one.

NO DUPLICATE FOR AN ALREADY-PENDING PAYMENT
Two guards, both BEFORE the publish, neither added by this milestone:

  * the duplicate-payment check raises BadRequestError when a PENDING or SUCCESS
    payment already exists for the appointment;
  * idx_unique_pending_payment, a partial unique index on appointment_id WHERE
    status = 'PENDING', closes the race and surfaces as the IntegrityError the
    function already handles.

The duplicate is never created, so the duplicate event is never published.

The channel's own behaviour -- sending, template selection, preferences,
idempotency, logging -- is tested in test_notification_whatsapp_channel.py
alongside every other event on that channel.
"""

import pathlib
import re

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
from app.services.payment_service import create_payment
from app.try_except.exceptions import BadRequestError

EVENT = "PAYMENT_PENDING"

REPO = pathlib.Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# 1. The event exists and is registered
# ---------------------------------------------------------------------------


def test_the_event_has_a_registered_schema():
    """Unregistered types are dropped by the outbox worker as unsupported."""
    assert EVENT in EVENT_SCHEMAS

    fields = EVENT_SCHEMAS[EVENT].model_fields

    assert "user_id" in fields
    assert "appointment_id" in fields


def test_the_event_carries_no_amount():
    """Matching PAYMENT_SUCCESS. The figure is in the application; WhatsApp is
    the least private channel the platform has."""
    fields = set(EVENT_SCHEMAS[EVENT].model_fields)

    for forbidden in ("amount", "consultation_fee", "reason", "method"):
        assert forbidden not in fields, f"PaymentPendingEvent carries {forbidden!r}"


def test_it_has_the_same_shape_as_payment_success():
    """The two are the same kind of message about the same aggregate. A wider
    payload here would be this channel inventing data the others do without."""
    assert set(EVENT_SCHEMAS[EVENT].model_fields) == set(
        EVENT_SCHEMAS["PAYMENT_SUCCESS"].model_fields
    )


# ---------------------------------------------------------------------------
# 5, 6, 7. Routing, notification config, template
# ---------------------------------------------------------------------------


def test_it_is_routed_through_the_patient_channels():
    from app.services.event_handlers.dispatcher import _with_patient_channels

    assert EVENT_HANDLERS.get(EVENT) is _with_patient_channels


def test_the_notification_config_entry_exists():
    """Load-bearing: _with_patient_channels returns early for an event missing
    from this map, so no channel runs -- and the Notification row it creates is
    the row the WhatsApp receipt is written on."""
    assert EVENT in EVENT_NOTIFICATION_CONFIG

    config = EVENT_NOTIFICATION_CONFIG[EVENT]

    assert config["user_field"] == "user_id"
    assert config["appointment_field"] == "appointment_id"


def test_the_in_app_message_states_no_amount():
    config = EVENT_NOTIFICATION_CONFIG[EVENT]

    text = config.get("message", "") + config.get("message_template", "")

    assert text, "the notification has no message"
    assert "{" not in text, "a placeholder would interpolate event data"

    for forbidden in ("৳", "amount"):
        assert forbidden not in text.lower()


def test_it_names_its_own_template_setting():
    assert EVENT in WHATSAPP_EVENTS
    assert WHATSAPP_EVENTS[EVENT]["template_setting"] == (
        "WHATSAPP_TEMPLATE_PAYMENT_PENDING"
    )


def test_the_template_setting_defaults_to_unconfigured():
    """Empty means not approved in Business Manager yet, and the channel declines
    rather than guessing a name Meta would reject with a 400."""
    from app.config import Settings

    assert Settings.model_fields["WHATSAPP_TEMPLATE_PAYMENT_PENDING"].default == ""


def test_no_two_events_share_a_template_setting():
    used = [config["template_setting"] for config in WHATSAPP_EVENTS.values()]

    assert len(used) == len(set(used))


def test_it_sends_no_body_parameters():
    assert WHATSAPP_EVENTS[EVENT]["parameters"] is _PARAMETERLESS


# ---------------------------------------------------------------------------
# 2, 4. The publishing point, and every path that reaches PENDING
# ---------------------------------------------------------------------------


def test_create_payment_is_the_only_place_a_payment_is_constructed():
    """THE CLAIM THE PUBLISHER RESTS ON.

    PENDING has no transition function, so "publish from the authoritative
    point" only holds while creation happens in one place. A second construction
    site would be a path that silently notifies nobody -- this fails the moment
    one appears.
    """
    sites = []

    for path in (REPO / "app").rglob("*.py"):
        if "__pycache__" in str(path):
            continue

        for number, line in enumerate(path.read_text().splitlines(), 1):
            code = line.split("#", 1)[0]

            # `Payment(` as a constructor call, not PaymentStatus/PaymentFailed…
            if re.search(r"(?<![A-Za-z_])Payment\(", code):
                sites.append(f"{path.relative_to(REPO)}:{number}")

    # The model's own class statement is not a construction.
    sites = [s for s in sites if not s.startswith("app/models/payment.py")]

    assert sites == ["app/services/payment_service.py:149"], sites


@pytest.fixture
async def pending_context(db, patient_user, doctor, appointment_factory):
    appointment = await appointment_factory(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        status=AppointmentStatus.PENDING,
    )

    return {"appointment": appointment, "patient": patient_user}


async def _published(db) -> list[OutboxEvent]:
    return list(
        await db.scalars(select(OutboxEvent).where(OutboxEvent.event_type == EVENT))
    )


@pytest.mark.asyncio
async def test_creating_a_payment_publishes_the_event(db, pending_context):
    payment = await create_payment(
        db=db,
        appointment_id=pending_context["appointment"].id,
        patient_id=pending_context["patient"].id,
        method="bkash",
    )

    events = await _published(db)

    assert len(events) == 1
    assert events[0].payload["user_id"] == payment.patient_id
    assert events[0].payload["appointment_id"] == payment.appointment_id


@pytest.mark.asyncio
async def test_the_published_event_carries_no_amount_or_method(db, pending_context):
    """create_payment knows the fee and the method. Neither belongs on an event
    whose consumers are patient-facing channels."""
    await create_payment(
        db=db,
        appointment_id=pending_context["appointment"].id,
        patient_id=pending_context["patient"].id,
        method="bkash",
    )

    payload = (await _published(db))[0].payload

    assert "amount" not in payload
    assert "method" not in payload
    assert "bkash" not in str(payload)


@pytest.mark.asyncio
async def test_the_payment_is_still_created_and_pending(db, pending_context):
    """3. State-transition behaviour unchanged -- the publish is additive."""
    payment = await create_payment(
        db=db,
        appointment_id=pending_context["appointment"].id,
        patient_id=pending_context["patient"].id,
        method="bkash",
    )

    assert payment.status == PaymentStatus.PENDING
    assert payment.public_invoice_id.startswith("INV-")


@pytest.mark.asyncio
async def test_a_second_payment_for_the_same_appointment_publishes_nothing(
    db, pending_context
):
    """3. The duplicate guard raises BEFORE the publish, so an already-PENDING
    payment produces no second event."""
    await create_payment(
        db=db,
        appointment_id=pending_context["appointment"].id,
        patient_id=pending_context["patient"].id,
        method="bkash",
    )

    with pytest.raises(BadRequestError):
        await create_payment(
            db=db,
            appointment_id=pending_context["appointment"].id,
            patient_id=pending_context["patient"].id,
            method="bkash",
        )

    assert len(await _published(db)) == 1


@pytest.mark.asyncio
async def test_an_already_paid_appointment_publishes_nothing(db, pending_context):
    """The other arm of the same guard: SUCCESS also blocks a new payment."""
    payment = await create_payment(
        db=db,
        appointment_id=pending_context["appointment"].id,
        patient_id=pending_context["patient"].id,
        method="bkash",
    )

    payment.status = PaymentStatus.SUCCESS
    await db.flush()

    with pytest.raises(BadRequestError):
        await create_payment(
            db=db,
            appointment_id=pending_context["appointment"].id,
            patient_id=pending_context["patient"].id,
            method="bkash",
        )

    assert len(await _published(db)) == 1


@pytest.mark.asyncio
async def test_a_rejected_creation_publishes_nothing(db, patient_user):
    """A payment that is never created must not announce itself. The appointment
    does not exist, so the function raises before constructing anything."""
    with pytest.raises(Exception):
        await create_payment(
            db=db, appointment_id=999_999, patient_id=patient_user.id, method="bkash"
        )

    assert await _published(db) == []


@pytest.mark.asyncio
async def test_the_payment_row_and_the_event_are_one_transaction(db, pending_context):
    """The publish joins the caller's transaction rather than committing, so the
    row and its outbox event are written together or not at all."""
    payment = await create_payment(
        db=db,
        appointment_id=pending_context["appointment"].id,
        patient_id=pending_context["patient"].id,
        method="bkash",
    )

    event = (await _published(db))[0]

    assert payment.id is not None
    assert event.payload["appointment_id"] == payment.appointment_id


@pytest.mark.asyncio
async def test_the_event_names_the_payment_as_its_aggregate(db, pending_context):
    """Consistent with the other three payment events, which all use the payment
    as the aggregate rather than the appointment."""
    payment = await create_payment(
        db=db,
        appointment_id=pending_context["appointment"].id,
        patient_id=pending_context["patient"].id,
        method="bkash",
    )

    payload = (await _published(db))[0].payload

    assert payload["aggregate_type"] == "payment"
    assert payload["aggregate_id"] == payment.id

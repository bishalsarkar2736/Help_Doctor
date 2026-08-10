"""WhatsApp, on the same rules as email.

The channel existed on paper — a preference, three database columns, three
indexes, a Meta Cloud API client and a handler — and nothing sent anything,
because the handler was wired nowhere.

Wiring it required one addition to the client. Meta only accepts free-form
messages inside a 24-hour window that the USER opens by writing to the business,
so a notification, being business-initiated, must reference a template approved
in Meta Business Manager. The client could only send documents. Templates are
approved outside this codebase, so their names come from configuration and the
channel declines to send without one rather than inventing a name that would be
rejected.

Two properties carry over from email deliberately, since two channels with two
notions of "who is this for" is how they drift apart:

PATIENTS ONLY, decided from the event's aggregate — appointment.patient_id — not
from a role column.

TENANCY WITHOUT CLINIC IDS, because a patient is a global identity and belongs
to every clinic that has treated them. What matters is being the patient of THIS
appointment.
"""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range

from app.config import get_settings
from app.core.time import UTC, utc_now
from app.models.appointment import Appointment, AppointmentStatus
from app.models.clinic import Clinic, ClinicStatus
from app.models.doctor import Doctor, DoctorStatus
from app.models.notification import Notification
from app.models.notification_preference import NotificationPreference
from app.models.outbox_event import OutboxEvent, OutboxStatus
from app.models.patient import Gender, Patient
from app.models.user import User, UserRole
from app.services.event_handlers import notification_whatsapp_handler
from app.services.event_handlers.notification_whatsapp_handler import (
    WHATSAPP_EVENTS,
)
from app.workers.outbox_worker import handle_event

# The PRESCRIPTION_ISSUED template name, spelled the way template_name_for does.
TEMPLATE = "helpdoctor_prescription_issued"


def template_name_for(event_type: str) -> str:
    """A distinct fake approved name per event.

    Distinct on purpose: a single shared name would let a test pass while the
    handler picked the wrong event's template, which is the mistake a per-event
    setting exists to prevent.
    """
    return f"helpdoctor_{event_type.lower()}"


@pytest.fixture
def channel_on(monkeypatch):
    """The channel enabled with an approved template name for EVERY event.

    All of them, not just the event under test. Empty template names are the
    default, so a fixture that configured only one would stop every other event
    at the template gate — and tests about the allowlist, the preference or the
    phone number would then pass without ever reaching the thing they name.
    """
    settings = get_settings()

    monkeypatch.setattr(settings, "WHATSAPP_NOTIFICATIONS_ENABLED", True)

    for event_type, config in WHATSAPP_EVENTS.items():
        monkeypatch.setattr(
            settings,
            config["template_setting"],
            template_name_for(event_type),
        )

    return settings


@pytest.fixture
def sent(monkeypatch):
    """Every template send, captured instead of posted to Meta."""
    messages = []

    async def _capture(**kwargs):
        messages.append(kwargs)
        return {}

    monkeypatch.setattr(
        notification_whatsapp_handler.WhatsAppService,
        "send_template",
        _capture,
    )

    return messages


async def _clinic(db, tag: str) -> dict:
    clinic = Clinic(name=f"WA {tag}", status=ClinicStatus.ACTIVE, timezone="UTC")
    db.add(clinic)
    await db.flush()

    doctor_user = User(
        email=f"wa-doc-{tag}@example.com", full_name=f"Dr {tag}",
        hashed_password="x", role=UserRole.DOCTOR, is_active=True,
        clinic_id=clinic.id,
    )
    db.add(doctor_user)
    await db.flush()

    doctor = Doctor(
        user_id=doctor_user.id, clinic_id=clinic.id, specialization="Medicine",
        experience_years=1, bio="b", status=DoctorStatus.APPROVED,
    )
    db.add(doctor)
    await db.flush()

    return {"clinic": clinic, "doctor": doctor, "doctor_user": doctor_user}


async def _patient(db, tag: str, *, phone="+8801944000111") -> User:
    user = User(
        email=f"wa-pat-{tag}@example.com", full_name=f"Patient {tag}",
        hashed_password="x", role=UserRole.PATIENT, is_active=True,
    )
    db.add(user)
    await db.flush()

    db.add(Patient(
        user_id=user.id, phone=phone, address="a",
        date_of_birth=utc_now().date(), gender=Gender.MALE,
    ))

    # whatsapp_enabled defaults to FALSE — the channel is opt-in, unlike email,
    # push and realtime. Opting in here is what stops the tests below passing
    # for the wrong reason: without it, "nothing was sent" would be true because
    # of the preference rather than because of the flag, the allowlist, the
    # missing template or the missing phone that each test is actually about.
    db.add(NotificationPreference(user_id=user.id, whatsapp_enabled=True))

    await db.flush()

    return user


async def _appointment(db, ctx, patient, *, hours=2, at=None) -> Appointment:
    start = at or (utc_now() + timedelta(hours=hours))

    appointment = Appointment(
        patient_id=patient.id, doctor_id=ctx["doctor"].id,
        clinic_id=ctx["clinic"].id, scheduled_at=start,
        status=AppointmentStatus.CONFIRMED,
        time_range=Range(start, start + Appointment.APPOINTMENT_DURATION),
    )
    db.add(appointment)
    await db.flush()

    return appointment


@pytest.fixture
async def clinic_a(db):
    ctx = await _clinic(db, "A")
    ctx["patient"] = await _patient(db, "a")
    ctx["appointment"] = await _appointment(db, ctx, ctx["patient"])
    return ctx


# The required fields of each event's schema beyond the common ones. Taken from
# app/schemas/event.py — an event whose payload does not validate never reaches
# the handler, so a test built on an invented field would assert nothing.
_EVENT_EXTRAS: dict[str, dict] = {
    "APPOINTMENT_CANCELLED": {
        "cancelled_by": {"id": 1, "role": "DOCTOR"},
        "reason": "x",
    },
    "PAYMENT_REFUNDED": {
        "payment_id": 1,
        "refund_transaction_id": "t",
        "refunded_amount": "500.00",
    },
    "PRESCRIPTION_REVISED": {
        "old_prescription_id": 1,
        "new_prescription_id": 2,
        "doctor_id": 1,
        "revision_number": 2,
    },
    "APPOINTMENT_CREATED": {
        "doctor_id": 1,
        "scheduled_at": utc_now().isoformat(),
    },
    "PATIENT_NEXT_IN_QUEUE": {"doctor_id": 1},
    "CONSULTATION_COMPLETED": {"doctor_id": 1},
}


def _payload(ctx, *, recipient_id, event_type="PRESCRIPTION_ISSUED"):
    # The recipient field is read from EVENT_NOTIFICATION_CONFIG rather than
    # guessed from the event name, because that is the map the dispatcher itself
    # passes to the handler. A test that guessed differently would address the
    # payload to a field the handler never reads.
    from app.services.event_handlers.notification_handler import (
        EVENT_NOTIFICATION_CONFIG,
    )

    field = EVENT_NOTIFICATION_CONFIG[event_type]["user_field"]

    payload = {
        "event_type": event_type,
        "schema_version": 1,
        "occurred_at": utc_now().isoformat(),
        "aggregate_type": "appointment",
        "aggregate_id": ctx["appointment"].id,
        "correlation_id": str(uuid.uuid4()),
        "appointment_id": ctx["appointment"].id,
        field: recipient_id,
    }

    payload.update(_EVENT_EXTRAS.get(event_type, {}))

    if event_type == "PRESCRIPTION_ISSUED":
        payload.update({
            "prescription_id": 1,
            "doctor_id": ctx["doctor"].id,
            "issued_at": utc_now().isoformat(),
        })

    return payload


async def _deliver(db, payload, event_type="PRESCRIPTION_ISSUED"):
    event = OutboxEvent(
        id=uuid.uuid4(), event_type=event_type, payload=payload, status=OutboxStatus.PENDING
    )
    db.add(event)
    await db.flush()

    await handle_event(db, event)

    return event


# ---------------------------------------------------------------------------
# The channel sends
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_patient_receives_a_template_message(
    db, clinic_a, channel_on, sent
):
    await _deliver(db, _payload(clinic_a, recipient_id=clinic_a["patient"].id))

    assert len(sent) == 1
    assert sent[0]["phone"] == "+8801944000111"
    assert sent[0]["template_name"] == TEMPLATE
    assert sent[0]["language"] == get_settings().WHATSAPP_TEMPLATE_LANGUAGE


@pytest.mark.asyncio
async def test_no_clinical_content_is_interpolated(db, clinic_a, channel_on, sent):
    """The approved template's own text carries the message; nothing clinical is
    passed from here, so no medicine or dosage can leak through a parameter."""
    await _deliver(db, _payload(clinic_a, recipient_id=clinic_a["patient"].id))

    assert not sent[0].get("body_parameters")


@pytest.mark.asyncio
async def test_no_prescription_document_is_sent(db, clinic_a, channel_on, sent):
    """The older, unwired handler uploads the prescription PDF. This path does
    not: WhatsApp is no more private than an inbox, and the same reasoning
    removed the PDF from email."""
    assert all("media_id" not in message for message in sent) or True

    await _deliver(db, _payload(clinic_a, recipient_id=clinic_a["patient"].id))

    assert "media_id" not in sent[0]
    assert "pdf_bytes" not in sent[0]


# ---------------------------------------------------------------------------
# Both gates must be open
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nothing_is_sent_while_the_channel_is_disabled(
    db, clinic_a, sent, monkeypatch
):
    """The default. A channel whose templates are not approved must not start
    failing against Meta the moment it is deployed.

    The template IS configured here, deliberately: everything else about this
    send is ready, so the flag is the only thing that can stop it. An earlier
    version of this test left the template empty and passed with the flag gate
    deleted — it was testing the template gate twice and the kill switch never.
    """
    settings = get_settings()

    assert settings.WHATSAPP_NOTIFICATIONS_ENABLED is False

    monkeypatch.setattr(
        settings, "WHATSAPP_TEMPLATE_PRESCRIPTION_ISSUED", TEMPLATE
    )

    await _deliver(db, _payload(clinic_a, recipient_id=clinic_a["patient"].id))

    assert sent == []


@pytest.mark.asyncio
async def test_nothing_is_sent_without_a_configured_template(
    db, clinic_a, sent, monkeypatch
):
    """Approved template names live in Meta Business Manager. Without one there
    is nothing valid to send, and guessing a name is a 400."""
    settings = get_settings()

    monkeypatch.setattr(settings, "WHATSAPP_NOTIFICATIONS_ENABLED", True)
    monkeypatch.setattr(settings, "WHATSAPP_TEMPLATE_PRESCRIPTION_ISSUED", "")

    await _deliver(db, _payload(clinic_a, recipient_id=clinic_a["patient"].id))

    assert sent == []


@pytest.mark.asyncio
async def test_whatsapp_enabled_is_respected(db, clinic_a, channel_on, sent):
    prefs = await db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == clinic_a["patient"].id
        )
    )
    prefs.whatsapp_enabled = False
    await db.flush()

    await _deliver(db, _payload(clinic_a, recipient_id=clinic_a["patient"].id))

    assert sent == []


@pytest.mark.asyncio
async def test_a_patient_without_a_phone_is_skipped(
    db, channel_on, sent
):
    ctx = await _clinic(db, "NoPhone")
    patient = User(
        email="wa-nophone@example.com", full_name="No Phone",
        hashed_password="x", role=UserRole.PATIENT, is_active=True,
    )
    db.add(patient)
    await db.flush()

    db.add(Patient(
        user_id=patient.id, phone="", address="a",
        date_of_birth=utc_now().date(), gender=Gender.MALE,
    ))
    db.add(NotificationPreference(user_id=patient.id, whatsapp_enabled=True))
    await db.flush()

    ctx["appointment"] = await _appointment(db, ctx, patient, hours=7)

    await _deliver(db, _payload(ctx, recipient_id=patient.id))

    assert sent == []


# ---------------------------------------------------------------------------
# Patients only, and the right patient
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_another_clinics_patient_is_refused(db, clinic_a, channel_on, sent):
    """By the existing recipient validation, which raises non-retryably — not by
    a clinic-id comparison."""
    from app.services.event_handlers.notification_handler import (
        RecipientNotPartyToEvent,
    )

    other = await _clinic(db, "B")
    outsider = await _patient(db, "b", phone="+8801944000222")
    await _appointment(db, other, outsider, hours=9)

    with pytest.raises(RecipientNotPartyToEvent):
        await _deliver(db, _payload(clinic_a, recipient_id=outsider.id))

    assert sent == []


@pytest.mark.asyncio
async def test_a_patient_who_is_not_this_appointments_patient_is_not_messaged(
    db, clinic_a, channel_on, sent
):
    """The patients-only gate, exercised for real.

    Called directly rather than through the outbox, and that is the point. Every
    route into this handler is guarded by something else that happens to stop the
    wrong recipient first — recipient validation refuses an outsider
    non-retryably, and a doctor has no Patient row and therefore no phone number
    to send to. So the composite cannot reach the state this gate exists for, and
    a version of this test written through _deliver passed with the gate deleted.

    The gate is still what holds the property, because the reasons above are
    accidents of other code: sourcing the phone from User instead of Patient, or
    a future event that fans out to both parties the way the appointment events
    do, would remove them. This asserts the handler's own contract — a recipient
    who is not appointment.patient_id is not messaged, whatever let them in.
    """
    from types import SimpleNamespace

    other = await _clinic(db, "C")
    stranger = await _patient(db, "c", phone="+8801944000333")
    await _appointment(db, other, stranger, hours=11)

    await notification_whatsapp_handler.handle_notification_whatsapp(
        db=db,
        validated=SimpleNamespace(
            patient_id=stranger.id,
            appointment_id=clinic_a["appointment"].id,
        ),
        event_id=uuid.uuid4(),
        event_type="PRESCRIPTION_ISSUED",
        user_field="patient_id",
    )

    assert sent == [], "a patient of another appointment was messaged"


@pytest.mark.asyncio
async def test_the_same_patient_is_messaged_by_two_clinics(
    db, channel_on, sent
):
    """Patients are global identities; being treated at two clinics must not
    suppress either clinic's message."""
    first = await _clinic(db, "One")
    second = await _clinic(db, "Two")

    patient = await _patient(db, "shared", phone="+8801944000333")

    for ctx, hours in ((first, 2), (second, 6)):
        ctx["appointment"] = await _appointment(db, ctx, patient, hours=hours)
        await _deliver(db, _payload(ctx, recipient_id=patient.id))

    assert len(sent) == 2


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------


def test_the_allowlist_is_exactly_the_approved_events():
    """Pinned, so an event cannot join the channel without this test saying so.

    Seven: the prescription event the channel started with, the three appointment
    changes, the reminder, and the two payment outcomes. Still ABSENT are
    running-late, completed, no-show, payment-failed and payment-pending — none of
    them is published by this platform, so an entry for them could never match a
    dispatched event.
    """
    assert set(WHATSAPP_EVENTS) == {
        "PRESCRIPTION_ISSUED",
        "APPOINTMENT_CONFIRMED",
        "APPOINTMENT_CANCELLED",
        "APPOINTMENT_RESCHEDULED",
        "APPOINTMENT_REMINDER",
        "PAYMENT_SUCCESS",
        "PAYMENT_REFUNDED",
    }


def test_every_allowlisted_event_names_a_real_setting():
    """A template setting that does not exist reads as "not approved yet" via
    getattr's default, so the event would silently never send."""
    settings = get_settings()

    for event_type, config in WHATSAPP_EVENTS.items():
        assert hasattr(settings, config["template_setting"]), (
            f"{event_type} names a setting that does not exist"
        )


def test_no_allowlisted_event_is_unpublishable():
    """Every WhatsApp event must be one the platform actually publishes.

    Checked against EVENT_SCHEMAS, which is what the outbox worker validates
    against: an event absent from there is dropped as unsupported before any
    handler runs.
    """
    from app.schemas.event_registry import EVENT_SCHEMAS

    assert set(WHATSAPP_EVENTS) <= set(EVENT_SCHEMAS)


def test_every_allowlisted_event_is_routed_to_the_channel():
    """The allowlist is necessary but not sufficient: an event whose dispatcher
    route skips the composite never reaches this handler at all. That was true
    of PAYMENT_SUCCESS until this milestone."""
    from app.services.event_handlers.dispatcher import (
        EVENT_HANDLERS,
        _with_patient_channels,
    )

    for event_type in WHATSAPP_EVENTS:
        assert EVENT_HANDLERS.get(event_type) is _with_patient_channels, (
            f"{event_type} is allowlisted but not routed to the channels"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type",
    ["PRESCRIPTION_REVISED", "APPOINTMENT_CREATED", "CONSULTATION_COMPLETED",
     "PATIENT_NEXT_IN_QUEUE"],
)
async def test_events_outside_the_allowlist_send_nothing(
    db, clinic_a, channel_on, sent, event_type
):
    """Real events, dispatched for real, that are not WhatsApp events.

    PRESCRIPTION_REVISED is the one that matters: it sends EMAIL. So the two
    channels legitimately cover different sets, which is only true if WhatsApp
    has its own allowlist rather than reusing email's.

    channel_on configures every template, so an event stopped here was stopped by
    the allowlist and not by missing configuration.
    """
    payload = _payload(
        clinic_a, recipient_id=clinic_a["patient"].id, event_type=event_type
    )

    await _deliver(db, payload, event_type=event_type)

    assert sent == [], f"{event_type} is not approved for WhatsApp"


# ---------------------------------------------------------------------------
# Idempotency and receipts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redelivery_does_not_message_twice(db, clinic_a, channel_on, sent):
    payload = _payload(clinic_a, recipient_id=clinic_a["patient"].id)

    event = await _deliver(db, payload)

    await handle_event(db, event)
    await handle_event(db, event)

    assert len(sent) == 1, f"redelivery sent {len(sent)} messages"


@pytest.mark.asyncio
async def test_the_receipt_lands_on_the_intended_recipient(
    db, clinic_a, channel_on, sent
):
    event = await _deliver(db, _payload(clinic_a, recipient_id=clinic_a["patient"].id))

    stored = await db.scalar(
        select(Notification).where(
            Notification.event_id == event.id,
            Notification.user_id == clinic_a["patient"].id,
        )
    )

    assert stored.whatsapp_delivered_at is not None
    assert stored.whatsapp_failed_at is None


@pytest.mark.asyncio
async def test_a_repeated_receipt_keeps_the_first_timestamp(
    db, clinic_a, channel_on, sent
):
    from app.services.notification_receipt_service import (
        mark_whatsapp_delivered,
    )

    event = await _deliver(db, _payload(clinic_a, recipient_id=clinic_a["patient"].id))

    stored = await db.scalar(
        select(Notification).where(Notification.event_id == event.id)
    )
    first = stored.whatsapp_delivered_at

    await mark_whatsapp_delivered(
        db=db, event_id=event.id, user_id=clinic_a["patient"].id
    )
    await db.refresh(stored)

    assert stored.whatsapp_delivered_at == first


@pytest.mark.asyncio
async def test_a_failure_marks_only_the_intended_recipient(
    db, clinic_a, channel_on, monkeypatch
):
    other = await _patient(db, "bystander", phone="+8801944000444")

    async def _explode(**kwargs):
        raise RuntimeError("meta rejected the template")

    monkeypatch.setattr(
        notification_whatsapp_handler.WhatsAppService, "send_template", _explode
    )

    event = OutboxEvent(
        id=uuid.uuid4(), event_type="PRESCRIPTION_ISSUED",
        payload=_payload(clinic_a, recipient_id=clinic_a["patient"].id),
        status=OutboxStatus.PENDING,
    )
    db.add(event)
    await db.flush()

    db.add(Notification(
        user_id=other.id, title="t", message="m",
        category="PRESCRIPTION", event_id=event.id,
    ))
    await db.flush()

    with pytest.raises(RuntimeError):
        await handle_event(db, event)

    await db.rollback()

    rows = {
        n.user_id: n
        for n in (
            await db.scalars(
                select(Notification).where(Notification.event_id == event.id)
            )
        ).all()
    }

    assert rows[clinic_a["patient"].id].whatsapp_failed_at is not None
    assert rows[other.id].whatsapp_failed_at is None


@pytest.mark.asyncio
async def test_a_failed_send_can_succeed_on_retry(
    db, clinic_a, channel_on, monkeypatch
):
    """A failure must not poison the guard: whatsapp_delivered_at is still NULL,
    so the outbox redelivery is allowed to try again."""
    attempts = []

    async def _fail_once(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise RuntimeError("meta timeout")
        return {}

    monkeypatch.setattr(
        notification_whatsapp_handler.WhatsAppService,
        "send_template",
        _fail_once,
    )

    event = OutboxEvent(
        id=uuid.uuid4(), event_type="PRESCRIPTION_ISSUED",
        payload=_payload(clinic_a, recipient_id=clinic_a["patient"].id),
        status=OutboxStatus.PENDING,
    )
    db.add(event)
    await db.flush()

    with pytest.raises(RuntimeError):
        await handle_event(db, event)

    await handle_event(db, event)

    assert len(attempts) == 2, "the retry was suppressed by the guard"

    stored = await db.scalar(
        select(Notification).where(Notification.event_id == event.id)
    )

    assert stored.whatsapp_delivered_at is not None
    assert stored.whatsapp_failed_at is not None, "the failure was erased"


# ---------------------------------------------------------------------------
# Channel independence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_whatsapp_failure_does_not_prevent_the_notification(
    db, clinic_a, channel_on, monkeypatch
):
    """The in-app notification is written before any channel runs, so it
    survives a channel that cannot deliver."""
    async def _explode(**kwargs):
        raise RuntimeError("meta down")

    monkeypatch.setattr(
        notification_whatsapp_handler.WhatsAppService, "send_template", _explode
    )

    event = OutboxEvent(
        id=uuid.uuid4(), event_type="PRESCRIPTION_ISSUED",
        payload=_payload(clinic_a, recipient_id=clinic_a["patient"].id),
        status=OutboxStatus.PENDING,
    )
    db.add(event)
    await db.flush()

    with pytest.raises(RuntimeError):
        await handle_event(db, event)

    stored = await db.scalar(
        select(Notification).where(Notification.event_id == event.id)
    )

    assert stored is not None


@pytest.mark.asyncio
async def test_disabling_whatsapp_does_not_disable_email(
    db, clinic_a, channel_on, monkeypatch
):
    """Separate preferences, separately checked."""
    from app.services.event_handlers import notification_email_handler

    emails = []

    async def _capture_email(**kwargs):
        emails.append(kwargs)

    monkeypatch.setattr(
        notification_email_handler, "send_email", _capture_email
    )

    async def _no_whatsapp(**kwargs):
        raise AssertionError("WhatsApp must not be sent")

    monkeypatch.setattr(
        notification_whatsapp_handler.WhatsAppService,
        "send_template",
        _no_whatsapp,
    )

    prefs = await db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == clinic_a["patient"].id
        )
    )
    prefs.whatsapp_enabled = False
    prefs.email_enabled = True
    await db.flush()

    await _deliver(db, _payload(clinic_a, recipient_id=clinic_a["patient"].id))

    assert len(emails) == 1


# ---------------------------------------------------------------------------
# The provider never calls Meta from a test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_client_makes_no_network_call_under_testing():
    """send_email has had this guard since it was written; this client did not,
    so wiring it live would have put graph.facebook.com in the test suite."""
    from app.services.whatsapp_service import WhatsAppService

    assert await WhatsAppService.send_template(
        phone="+880000", template_name="x"
    ) == {}
    assert await WhatsAppService.send_document(
        phone="+880000", media_id="m", filename="f.pdf"
    ) == {}
    assert await WhatsAppService.upload_media(
        pdf_bytes=b"x", filename="f.pdf"
    ) == {}


# ---------------------------------------------------------------------------
# Every approved event, end to end
# ---------------------------------------------------------------------------

# The five events added to the channel, plus the one it started with. Listed
# explicitly rather than read from WHATSAPP_EVENTS: a test that iterates the
# thing under test still passes when an entry is deleted from it.
ALL_EVENTS = [
    "PRESCRIPTION_ISSUED",
    "APPOINTMENT_CONFIRMED",
    "APPOINTMENT_CANCELLED",
    "APPOINTMENT_RESCHEDULED",
    "APPOINTMENT_REMINDER",
    "PAYMENT_SUCCESS",
    "PAYMENT_REFUNDED",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ALL_EVENTS)
async def test_each_approved_event_messages_the_patient(
    db, clinic_a, channel_on, sent, event_type
):
    """Dispatched through the outbox exactly as production would, so this covers
    the schema, the dispatcher route, the allowlist and the send together."""
    await _deliver(
        db,
        _payload(
            clinic_a,
            recipient_id=clinic_a["patient"].id,
            event_type=event_type,
        ),
        event_type=event_type,
    )

    assert len(sent) == 1, f"{event_type} sent {len(sent)} messages"

    # Its OWN template, not another event's. The names are distinct per event,
    # so a handler reading the wrong setting fails here.
    assert sent[0]["template_name"] == template_name_for(event_type)
    assert sent[0]["phone"] == "+8801944000111"


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ALL_EVENTS)
async def test_the_kill_switch_stops_every_event(
    db, clinic_a, channel_on, sent, monkeypatch, event_type
):
    """One flag has to be enough to silence the channel, whatever is approved."""
    monkeypatch.setattr(channel_on, "WHATSAPP_NOTIFICATIONS_ENABLED", False)

    await _deliver(
        db,
        _payload(
            clinic_a, recipient_id=clinic_a["patient"].id, event_type=event_type
        ),
        event_type=event_type,
    )

    assert sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ALL_EVENTS)
async def test_each_event_needs_its_own_template(
    db, clinic_a, channel_on, sent, monkeypatch, event_type
):
    """Only this event's template name is cleared; the other five stay
    configured. So an event that still sends is reading the wrong setting."""
    monkeypatch.setattr(
        channel_on, WHATSAPP_EVENTS[event_type]["template_setting"], ""
    )

    await _deliver(
        db,
        _payload(
            clinic_a, recipient_id=clinic_a["patient"].id, event_type=event_type
        ),
        event_type=event_type,
    )

    assert sent == [], f"{event_type} sent without an approved template"


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ALL_EVENTS)
async def test_the_preference_governs_every_event(
    db, clinic_a, channel_on, sent, event_type
):
    prefs = await db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == clinic_a["patient"].id
        )
    )
    prefs.whatsapp_enabled = False
    await db.flush()

    await _deliver(
        db,
        _payload(
            clinic_a, recipient_id=clinic_a["patient"].id, event_type=event_type
        ),
        event_type=event_type,
    )

    assert sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ALL_EVENTS)
async def test_a_missing_phone_stops_every_event(
    db, channel_on, sent, event_type
):
    ctx = await _clinic(db, f"nophone-{event_type}")
    patient = await _patient(db, f"nophone-{event_type}", phone="")
    ctx["patient"] = patient
    ctx["appointment"] = await _appointment(db, ctx, patient, hours=5)

    await _deliver(
        db,
        _payload(ctx, recipient_id=patient.id, event_type=event_type),
        event_type=event_type,
    )

    assert sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ALL_EVENTS)
async def test_every_event_records_delivery_and_does_not_repeat(
    db, clinic_a, channel_on, sent, event_type
):
    """Requirements 10, 11 and 13 together: the receipt is written, it is written
    against the recipient, and a redelivery of the same event does nothing."""
    event = await _deliver(
        db,
        _payload(
            clinic_a, recipient_id=clinic_a["patient"].id, event_type=event_type
        ),
        event_type=event_type,
    )

    stored = await db.scalar(
        select(Notification).where(
            Notification.event_id == event.id,
            Notification.user_id == clinic_a["patient"].id,
        )
    )

    assert stored is not None
    assert stored.whatsapp_delivered_at is not None

    await handle_event(db, event)
    await handle_event(db, event)

    assert len(sent) == 1, f"{event_type} was redelivered {len(sent)} times"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type", ["APPOINTMENT_CONFIRMED", "PAYMENT_REFUNDED"]
)
async def test_a_failure_stays_retryable_for_the_new_events(
    db, clinic_a, channel_on, monkeypatch, event_type
):
    """A provider failure must record the failure, leave delivered_at unset, and
    propagate — otherwise the outbox marks the event processed and the patient is
    never told."""
    attempts = []

    async def _fail(**kwargs):
        attempts.append(kwargs)
        raise RuntimeError("meta is down")

    monkeypatch.setattr(
        notification_whatsapp_handler.WhatsAppService, "send_template", _fail
    )

    payload = _payload(
        clinic_a, recipient_id=clinic_a["patient"].id, event_type=event_type
    )

    with pytest.raises(RuntimeError):
        await _deliver(db, payload, event_type=event_type)

    stored = await db.scalar(
        select(Notification).where(
            Notification.user_id == clinic_a["patient"].id
        ).order_by(Notification.id.desc())
    )

    assert stored.whatsapp_delivered_at is None
    assert stored.whatsapp_failed_at is not None
    assert stored.whatsapp_error

    # And the retry succeeds, because nothing recorded it as delivered.
    ok = []

    async def _ok(**kwargs):
        ok.append(kwargs)
        return {}

    monkeypatch.setattr(
        notification_whatsapp_handler.WhatsAppService, "send_template", _ok
    )

    await _deliver(db, payload, event_type=event_type)

    assert len(ok) == 1


# ---------------------------------------------------------------------------
# What lands in the message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type",
    ["APPOINTMENT_CONFIRMED", "APPOINTMENT_CANCELLED", "APPOINTMENT_RESCHEDULED"],
)
async def test_the_appointment_date_and_time_are_in_the_clinics_timezone(
    db, channel_on, sent, event_type
):
    """The mapping that matters, and the one a UTC server gets wrong.

    20:00 UTC on 15 December is 02:00 the NEXT MORNING in Dhaka, so a handler
    that skipped the conversion would announce both the wrong time and the wrong
    DATE — and the patient has no way to spot it.
    """
    ctx = await _clinic(db, f"tz-{event_type}")
    ctx["clinic"].timezone = "Asia/Dhaka"
    await db.flush()

    patient = await _patient(db, f"tz-{event_type}")
    ctx["patient"] = patient
    ctx["appointment"] = await _appointment(
        db, ctx, patient,
        at=datetime(2026, 12, 15, 20, 0, tzinfo=UTC),
    )

    await _deliver(
        db,
        _payload(ctx, recipient_id=patient.id, event_type=event_type),
        event_type=event_type,
    )

    assert sent[0]["body_parameters"] == ["16 Dec 2026", "02:00 AM"]


@pytest.mark.asyncio
async def test_the_refunded_amount_is_mapped_from_the_event(
    db, clinic_a, channel_on, sent
):
    """The one event that carries an amount."""
    payload = _payload(
        clinic_a,
        recipient_id=clinic_a["patient"].id,
        event_type="PAYMENT_REFUNDED",
    )
    payload["refunded_amount"] = "1250.50"

    await _deliver(db, payload, event_type="PAYMENT_REFUNDED")

    assert sent[0]["body_parameters"] == ["৳1250.50"]


@pytest.mark.asyncio
async def test_payment_success_sends_no_amount(db, clinic_a, channel_on, sent):
    """PaymentSuccessEvent has no amount field. Rather than reading one off the
    Payment table — which would be this channel inventing event data — the
    template is sent with no parameters at all."""
    await _deliver(
        db,
        _payload(
            clinic_a,
            recipient_id=clinic_a["patient"].id,
            event_type="PAYMENT_SUCCESS",
        ),
        event_type="PAYMENT_SUCCESS",
    )

    assert not sent[0].get("body_parameters")


@pytest.mark.asyncio
async def test_no_cancellation_reason_reaches_whatsapp(
    db, clinic_a, channel_on, sent
):
    """The cancellation event carries free text typed by staff. It is unbounded
    and could name a condition, so none of it is sent."""
    payload = _payload(
        clinic_a,
        recipient_id=clinic_a["patient"].id,
        event_type="APPOINTMENT_CANCELLED",
    )
    payload["reason"] = "patient has suspected tuberculosis"

    await _deliver(db, payload, event_type="APPOINTMENT_CANCELLED")

    emitted = str(sent[0])

    assert "tuberculosis" not in emitted
    assert "suspected" not in emitted


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ALL_EVENTS)
async def test_no_database_id_reaches_the_message(
    db, clinic_a, channel_on, sent, event_type
):
    """No parameter may carry an internal id.

    Asserted against the ids this event actually has to hand — appointment,
    patient, doctor and clinic — because those are the ones a careless parameter
    list would pick up.
    """
    await _deliver(
        db,
        _payload(
            clinic_a, recipient_id=clinic_a["patient"].id, event_type=event_type
        ),
        event_type=event_type,
    )

    parameters = sent[0].get("body_parameters") or []

    forbidden = {
        str(clinic_a["appointment"].id),
        str(clinic_a["patient"].id),
        str(clinic_a["doctor"].id),
        str(clinic_a["clinic"].id),
    }

    for value in parameters:
        assert value not in forbidden, f"{event_type} sent a database id"


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ALL_EVENTS)
async def test_no_provider_credential_reaches_the_message(
    db, clinic_a, channel_on, sent, event_type
):
    settings = get_settings()

    await _deliver(
        db,
        _payload(
            clinic_a, recipient_id=clinic_a["patient"].id, event_type=event_type
        ),
        event_type=event_type,
    )

    emitted = str(sent[0])

    assert settings.WHATSAPP_ACCESS_TOKEN not in emitted
    assert settings.WHATSAPP_PHONE_NUMBER_ID not in emitted


@pytest.mark.asyncio
async def test_the_prescription_message_is_unchanged(
    db, clinic_a, channel_on, sent
):
    """The event the channel started with must behave exactly as before: its own
    template, and no parameters."""
    await _deliver(db, _payload(clinic_a, recipient_id=clinic_a["patient"].id))

    assert sent[0]["template_name"] == TEMPLATE
    assert not sent[0].get("body_parameters")


# ---------------------------------------------------------------------------
# Recipient rules, for the events that fan out to both parties
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type",
    ["APPOINTMENT_CONFIRMED", "APPOINTMENT_CANCELLED", "PAYMENT_SUCCESS"],
)
async def test_the_wrong_patient_is_refused_for_every_event(
    db, clinic_a, channel_on, sent, event_type
):
    """A patient of another clinic, addressed with this clinic's appointment.

    Refused by the existing recipient validation, non-retryably — not by a
    clinic-id comparison, which would be meaningless for a global patient.
    """
    from app.services.event_handlers.notification_handler import (
        RecipientNotPartyToEvent,
    )

    other = await _clinic(db, f"wrong-{event_type}")
    outsider = await _patient(db, f"wrong-{event_type}", phone="+8801944000999")
    await _appointment(db, other, outsider, hours=13)

    with pytest.raises(RecipientNotPartyToEvent):
        await _deliver(
            db,
            _payload(clinic_a, recipient_id=outsider.id, event_type=event_type),
            event_type=event_type,
        )

    assert sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type", ["APPOINTMENT_CONFIRMED", "PAYMENT_REFUNDED"]
)
async def test_the_same_patient_is_messaged_by_both_clinics_for_new_events(
    db, channel_on, sent, event_type
):
    """Patients are global identities. Being treated at two clinics must not
    make either clinic's notification look like a cross-tenant leak."""
    patient = await _patient(db, f"shared-{event_type}", phone="+8801944000444")

    for tag, hours in (("one", 3), ("two", 8)):
        ctx = await _clinic(db, f"{tag}-{event_type}")
        ctx["patient"] = patient
        ctx["appointment"] = await _appointment(db, ctx, patient, hours=hours)

        await _deliver(
            db,
            _payload(ctx, recipient_id=patient.id, event_type=event_type),
            event_type=event_type,
        )

    assert len(sent) == 2


# ---------------------------------------------------------------------------
# The other channels are untouched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_payment_success_still_sends_no_email(
    db, clinic_a, channel_on, sent, monkeypatch
):
    """PAYMENT_SUCCESS was moved onto the composite route so WhatsApp could see
    it. Email must not have come along: EMAIL_EVENTS does not list it, and that
    allowlist is the only thing standing between this route change and a new
    email nobody asked for."""
    emails = []

    async def _capture_email(**kwargs):
        emails.append(kwargs)

    monkeypatch.setattr(
        "app.services.event_handlers.notification_email_handler.send_email",
        _capture_email,
    )

    await _deliver(
        db,
        _payload(
            clinic_a,
            recipient_id=clinic_a["patient"].id,
            event_type="PAYMENT_SUCCESS",
        ),
        event_type="PAYMENT_SUCCESS",
    )

    assert len(sent) == 1, "WhatsApp should have sent"
    assert emails == [], "PAYMENT_SUCCESS is not an email event"


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ALL_EVENTS)
async def test_the_in_app_notification_is_still_written(
    db, clinic_a, channel_on, sent, event_type
):
    """WhatsApp is an addition. The stored notification — the record the patient
    sees in the app, and the one the receipts hang off — must be unaffected."""
    event = await _deliver(
        db,
        _payload(
            clinic_a, recipient_id=clinic_a["patient"].id, event_type=event_type
        ),
        event_type=event_type,
    )

    stored = await db.scalar(
        select(Notification).where(
            Notification.event_id == event.id,
            Notification.user_id == clinic_a["patient"].id,
        )
    )

    assert stored is not None
    assert stored.title
    assert stored.message


@pytest.mark.asyncio
async def test_a_whatsapp_failure_does_not_lose_the_in_app_notification(
    db, clinic_a, channel_on, monkeypatch
):
    async def _fail(**kwargs):
        raise RuntimeError("meta is down")

    monkeypatch.setattr(
        notification_whatsapp_handler.WhatsAppService, "send_template", _fail
    )

    payload = _payload(
        clinic_a,
        recipient_id=clinic_a["patient"].id,
        event_type="APPOINTMENT_CONFIRMED",
    )

    with pytest.raises(RuntimeError):
        await _deliver(db, payload, event_type="APPOINTMENT_CONFIRMED")

    stored = await db.scalar(
        select(Notification).where(
            Notification.user_id == clinic_a["patient"].id
        ).order_by(Notification.id.desc())
    )

    assert stored is not None
    assert stored.title

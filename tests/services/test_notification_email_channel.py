"""Email for the six events a patient should hear about out of band.

Email previously existed for one event, PRESCRIPTION_ISSUED, through a dedicated
handler that attaches the prescription PDF. That handler is unchanged; this
covers the generic path added for the other five and the properties the channel
has to hold.

The two that matter most, because neither can be read off a role column:

PATIENTS ONLY. Three of these events fan out to BOTH parties under one event
type — the same APPOINTMENT_CANCELLED is published once to the patient and once
to the doctor, with the same configuration. So "is this the patient?" is answered
from the aggregate: event → appointment_id → appointment.patient_id.

TENANCY WITHOUT CLINIC IDS. Comparing clinic ids would say nothing about a
patient, who is a global identity belonging to every clinic that has treated
them. What matters is whether they are the patient OF THIS APPOINTMENT — which a
patient of another clinic cannot be, and which the same patient CAN be at two
clinics at once.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range

from app.core.time import utc_now
from app.models.appointment import Appointment, AppointmentStatus
from app.models.clinic import Clinic, ClinicStatus
from app.models.doctor import Doctor, DoctorStatus
from app.models.notification import Notification
from app.models.notification_preference import NotificationPreference
from app.models.outbox_event import OutboxEvent, OutboxStatus
from app.models.patient import Gender, Patient
from app.models.user import User, UserRole
from app.services.event_handlers import notification_email_handler
from app.services.event_handlers.notification_email_handler import EMAIL_EVENTS
from app.services.event_handlers.notification_handler import (
    EVENT_NOTIFICATION_CONFIG,
    RecipientNotPartyToEvent,
)
from app.workers.outbox_worker import handle_event

SIX = [
    "APPOINTMENT_CONFIRMED",
    "APPOINTMENT_CANCELLED",
    "APPOINTMENT_RESCHEDULED",
    "PAYMENT_REFUNDED",
    "PRESCRIPTION_ISSUED",
    "PRESCRIPTION_REVISED",
]


@pytest.fixture
def sent(monkeypatch):
    """Every email the generic handler would send, captured.

    send_email itself returns early when TESTING=1, so patching here is what
    makes the send observable at all.
    """
    messages = []

    async def _capture(**kwargs):
        messages.append(kwargs)

    monkeypatch.setattr(notification_email_handler, "send_email", _capture)

    return messages


async def _clinic(db, tag: str) -> dict:
    clinic = Clinic(
        name=f"Email {tag}", status=ClinicStatus.ACTIVE, timezone="UTC"
    )
    db.add(clinic)
    await db.flush()

    doctor_user = User(
        email=f"email-doc-{tag}@example.com", full_name=f"Dr {tag}",
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


async def _patient(db, tag: str) -> User:
    user = User(
        email=f"email-pat-{tag}@example.com", full_name=f"Patient {tag}",
        hashed_password="x", role=UserRole.PATIENT, is_active=True,
    )
    db.add(user)
    await db.flush()

    db.add(Patient(
        user_id=user.id, phone=f"+8801955{abs(hash(tag)) % 1000000:06d}",
        address="a", date_of_birth=utc_now().date(), gender=Gender.MALE,
    ))
    await db.flush()

    return user


async def _appointment(db, ctx, patient, *, hours=2) -> Appointment:
    start = utc_now() + timedelta(hours=hours)

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


def _payload(event_type, *, appointment, recipient_id, extra=None):
    config = EVENT_NOTIFICATION_CONFIG[event_type]

    payload = {
        "event_type": event_type,
        "schema_version": 1,
        "occurred_at": utc_now().isoformat(),
        "aggregate_type": "appointment",
        "aggregate_id": appointment.id,
        "correlation_id": str(uuid.uuid4()),
        "appointment_id": appointment.id,
        config["user_field"]: recipient_id,
    }

    payload.update(extra or {})
    return payload


async def _deliver(db, event_type, payload):
    event = OutboxEvent(
        id=uuid.uuid4(), event_type=event_type, payload=payload, status=OutboxStatus.PENDING
    )
    db.add(event)
    await db.flush()

    await handle_event(db, event)

    return event


EXTRAS = {
    "APPOINTMENT_CANCELLED": {
        "cancelled_by": {"id": 1, "role": "DOCTOR"}, "reason": "x",
    },
    "PAYMENT_REFUNDED": {
        "payment_id": 1, "refund_transaction_id": "t",
        "refunded_amount": "500.00",
    },
    "PRESCRIPTION_REVISED": {
        "old_prescription_id": 1, "new_prescription_id": 2,
        "doctor_id": 1, "revision_number": 2,
    },
}


# ---------------------------------------------------------------------------
# The five generic events reach the patient
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type",
    [
        "APPOINTMENT_CONFIRMED",
        "APPOINTMENT_CANCELLED",
        "APPOINTMENT_RESCHEDULED",
        "PAYMENT_REFUNDED",
        "PRESCRIPTION_REVISED",
    ],
)
async def test_the_patient_is_emailed(db, clinic_a, sent, event_type):
    await _deliver(
        db, event_type,
        _payload(
            event_type, appointment=clinic_a["appointment"],
            recipient_id=clinic_a["patient"].id,
            extra=EXTRAS.get(event_type),
        ),
    )

    assert len(sent) == 1, f"{event_type} sent no email"
    assert sent[0]["to"] == clinic_a["patient"].email


@pytest.mark.asyncio
async def test_the_refund_email_carries_the_amount(db, clinic_a, sent):
    """Allowed explicitly, and already in the in-app notification."""
    await _deliver(
        db, "PAYMENT_REFUNDED",
        _payload(
            "PAYMENT_REFUNDED", appointment=clinic_a["appointment"],
            recipient_id=clinic_a["patient"].id,
            extra=EXTRAS["PAYMENT_REFUNDED"],
        ),
    )

    assert "500.00" in sent[0]["html_body"]


@pytest.mark.asyncio
async def test_prescription_issued_emails_through_the_safe_path(
    db, clinic_a, sent
):
    """It used to have a dedicated handler that attached the prescription PDF.

    Both prescription events now run through this one path, so neither can
    drift from the other on what it discloses.
    """
    await _deliver(
        db, "PRESCRIPTION_ISSUED",
        _payload(
            "PRESCRIPTION_ISSUED", appointment=clinic_a["appointment"],
            recipient_id=clinic_a["patient"].id,
            extra={
                "prescription_id": 1,
                "doctor_id": clinic_a["doctor"].id,
                "issued_at": utc_now().isoformat(),
            },
        ),
    )

    assert len(sent) == 1
    assert sent[0]["to"] == clinic_a["patient"].email


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type", ["PRESCRIPTION_ISSUED", "PRESCRIPTION_REVISED"]
)
async def test_no_prescription_email_carries_an_attachment(
    db, clinic_a, sent, event_type
):
    """The change asked for: the prescription PDF is no longer emailed.

    A PDF in an inbox is the whole document — medicines, dosages, the lot —
    sitting somewhere far less protected than a logged-in session, and often
    mirrored to a phone and a laptop. Asserted for both events, because the
    reason applies equally to each.
    """
    extra = (
        {
            "prescription_id": 1, "doctor_id": clinic_a["doctor"].id,
            "issued_at": utc_now().isoformat(),
        }
        if event_type == "PRESCRIPTION_ISSUED"
        else EXTRAS["PRESCRIPTION_REVISED"]
    )

    await _deliver(
        db, event_type,
        _payload(
            event_type, appointment=clinic_a["appointment"],
            recipient_id=clinic_a["patient"].id, extra=extra,
        ),
    )

    assert len(sent) == 1

    assert not sent[0].get("attachments"), (
        f"{event_type} email still carries an attachment"
    )

    body = (sent[0]["html_body"] or "") + sent[0]["body"]

    assert "attach" not in body.lower(), (
        "the email still tells the patient to look for an attachment"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type", ["PRESCRIPTION_ISSUED", "PRESCRIPTION_REVISED"]
)
async def test_no_prescription_email_carries_clinical_content(
    db, clinic_a, sent, event_type
):
    """Named medicines, dosages and diagnoses stay behind authentication.

    The prescription this patient actually has is built in the fixture, so the
    assertion is against real content rather than invented strings.
    """
    from app.models.prescription import (
        Prescription,
        PrescriptionItem,
        PrescriptionStatus,
    )

    prescription = Prescription(
        appointment_id=clinic_a["appointment"].id,
        doctor_id=clinic_a["doctor"].id,
        patient_id=clinic_a["patient"].id,
        status=PrescriptionStatus.ISSUED,
        notes="Diagnosis: hypertension", issued_at=utc_now(),
        clinic_id=clinic_a["clinic"].id, revision_number=1,
        is_latest_revision=True,
    )
    db.add(prescription)
    await db.flush()

    db.add(PrescriptionItem(
        prescription_id=prescription.id, medicine_name="Napa",
        dosage="500mg", frequency="2 times daily", duration_days=5,
        instructions="After meal",
    ))
    await db.flush()

    extra = (
        {
            "prescription_id": prescription.id,
            "doctor_id": clinic_a["doctor"].id,
            "issued_at": utc_now().isoformat(),
        }
        if event_type == "PRESCRIPTION_ISSUED"
        else {
            "old_prescription_id": prescription.id,
            "new_prescription_id": prescription.id,
            "doctor_id": clinic_a["doctor"].id, "revision_number": 2,
        }
    )

    await _deliver(
        db, event_type,
        _payload(
            event_type, appointment=clinic_a["appointment"],
            recipient_id=clinic_a["patient"].id, extra=extra,
        ),
    )

    everything = (
        sent[0]["subject"] + sent[0]["body"] + (sent[0]["html_body"] or "")
    ).lower()

    for leaked in ("napa", "500mg", "2 times daily", "after meal",
                   "hypertension", "diagnosis"):
        assert leaked not in everything, f"{event_type} email leaked {leaked!r}"

    # Internal identifiers, checked against the VISIBLE text.
    #
    # Searching the raw HTML for str(id) is unsound for small integers: the
    # first version of this failed because the prescription's id was 2 and the
    # markup contains "<h2>". Stripping the tags first also makes the assertion
    # stronger — no digit reaches the reader at all, so no id can, whatever it
    # happens to be.
    import re

    visible = re.sub(r"<[^>]+>", " ", sent[0]["html_body"] or "")

    assert not re.search(r"\d", visible), (
        f"{event_type} email shows a number to the reader: {visible.strip()!r}"
    )

    for identifier in (
        prescription.id, clinic_a["appointment"].id, clinic_a["patient"].id,
    ):
        assert str(identifier) not in visible, (
            f"{event_type} email exposes internal id {identifier}"
        )


@pytest.mark.asyncio
async def test_the_prescription_pdf_is_still_available_in_the_app(db, clinic_a):
    """Removing it from email must not remove it from the product.

    The authenticated download endpoint is where the document belongs, and it
    still generates one.
    """
    from app.services.prescription_pdf_service import generate_prescription_pdf

    assert callable(generate_prescription_pdf)

    from pathlib import Path

    route_source = (
        Path(__file__).parent.parent.parent
        / "app" / "api" / "routes" / "prescription.py"
    ).read_text()

    assert "generate_prescription_pdf" in route_source, (
        "the authenticated PDF download no longer generates a document"
    )


def test_no_email_path_attaches_a_prescription_pdf():
    """A guard on the shape, so the attachment cannot come back quietly.

    The PDF-attaching email handler and its sender were removed; what must not
    reappear is an email path that generates one.
    """
    import re
    from pathlib import Path

    handlers = (
        Path(__file__).parent.parent.parent
        / "app" / "services" / "event_handlers"
    )

    offenders = []

    for path in handlers.glob("*.py"):
        source = path.read_text()

        if "whatsapp" in path.name:
            # Out of scope for this milestone, and unwired.
            continue

        if re.search(r"generate_prescription_pdf|attachments\s*=", source):
            offenders.append(path.name)

    assert not offenders, (
        f"an email handler builds an attachment again: {offenders}"
    )


# ---------------------------------------------------------------------------
# Patients only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type",
    ["APPOINTMENT_CONFIRMED", "APPOINTMENT_CANCELLED", "APPOINTMENT_RESCHEDULED"],
)
async def test_the_doctor_half_of_the_fan_out_is_not_emailed(
    db, clinic_a, sent, event_type
):
    """The same event type, addressed to the doctor. A role check could not
    distinguish these two deliveries; the appointment's patient_id does."""
    await _deliver(
        db, event_type,
        _payload(
            event_type, appointment=clinic_a["appointment"],
            recipient_id=clinic_a["doctor_user"].id,
            extra=EXTRAS.get(event_type),
        ),
    )

    assert sent == [], f"{event_type} emailed the doctor"


# ---------------------------------------------------------------------------
# Tenancy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_another_clinics_patient_is_refused_by_recipient_validation(
    db, clinic_a, sent
):
    """Not by a clinic-id comparison — by the existing validation, which raises
    non-retryably and preserves the event for dead-letter inspection."""
    other = await _clinic(db, "B")
    outsider = await _patient(db, "b")
    await _appointment(db, other, outsider, hours=5)

    with pytest.raises(RecipientNotPartyToEvent):
        await _deliver(
            db, "APPOINTMENT_CONFIRMED",
            _payload(
                "APPOINTMENT_CONFIRMED", appointment=clinic_a["appointment"],
                recipient_id=outsider.id,
            ),
        )

    assert sent == []


@pytest.mark.asyncio
async def test_one_patient_is_emailed_by_two_clinics_for_their_own_events(
    db, sent
):
    """Patients are global identities. Being treated at two clinics is normal
    and must not suppress either clinic's mail — the test a clinic-id
    comparison would fail."""
    first = await _clinic(db, "One")
    second = await _clinic(db, "Two")

    patient = await _patient(db, "shared")

    here = await _appointment(db, first, patient, hours=2)
    there = await _appointment(db, second, patient, hours=6)

    for appointment in (here, there):
        await _deliver(
            db, "APPOINTMENT_CONFIRMED",
            _payload(
                "APPOINTMENT_CONFIRMED", appointment=appointment,
                recipient_id=patient.id,
            ),
        )

    assert len(sent) == 2
    assert {m["to"] for m in sent} == {patient.email}


# ---------------------------------------------------------------------------
# Preference, and channel independence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_enabled_sends(db, clinic_a, sent):
    prefs = NotificationPreference(
        user_id=clinic_a["patient"].id, email_enabled=True
    )
    db.add(prefs)
    await db.flush()

    await _deliver(
        db, "APPOINTMENT_CONFIRMED",
        _payload(
            "APPOINTMENT_CONFIRMED", appointment=clinic_a["appointment"],
            recipient_id=clinic_a["patient"].id,
        ),
    )

    assert len(sent) == 1


@pytest.mark.asyncio
async def test_email_disabled_does_not_send(db, clinic_a, sent):
    prefs = NotificationPreference(
        user_id=clinic_a["patient"].id, email_enabled=False
    )
    db.add(prefs)
    await db.flush()

    await _deliver(
        db, "APPOINTMENT_CONFIRMED",
        _payload(
            "APPOINTMENT_CONFIRMED", appointment=clinic_a["appointment"],
            recipient_id=clinic_a["patient"].id,
        ),
    )

    assert sent == []


@pytest.mark.asyncio
async def test_disabling_email_still_creates_the_notification(
    db, clinic_a, sent
):
    prefs = NotificationPreference(
        user_id=clinic_a["patient"].id, email_enabled=False
    )
    db.add(prefs)
    await db.flush()

    event = await _deliver(
        db, "APPOINTMENT_CONFIRMED",
        _payload(
            "APPOINTMENT_CONFIRMED", appointment=clinic_a["appointment"],
            recipient_id=clinic_a["patient"].id,
        ),
    )

    stored = await db.scalar(
        select(Notification).where(Notification.event_id == event.id)
    )

    assert stored is not None
    assert sent == []


@pytest.mark.asyncio
async def test_disabling_email_does_not_disable_push(db, clinic_a, monkeypatch):
    """Separate preferences, separately checked."""
    from app.task.notification_tasks import send_push_notification_task

    pushes = []
    monkeypatch.setattr(
        send_push_notification_task, "delay", lambda **kw: pushes.append(kw)
    )

    async def _no_email(**kwargs):
        raise AssertionError("email must not be sent")

    monkeypatch.setattr(notification_email_handler, "send_email", _no_email)

    prefs = NotificationPreference(
        user_id=clinic_a["patient"].id, email_enabled=False, push_enabled=True
    )
    db.add(prefs)
    await db.flush()

    await _deliver(
        db, "APPOINTMENT_CONFIRMED",
        _payload(
            "APPOINTMENT_CONFIRMED", appointment=clinic_a["appointment"],
            recipient_id=clinic_a["patient"].id,
        ),
    )

    assert len(pushes) == 1


@pytest.mark.asyncio
async def test_disabling_email_does_not_disable_realtime(
    db, clinic_a, monkeypatch
):
    from app.services.event_handlers import notification_handler

    realtime = []

    async def _capture(**kwargs):
        realtime.append(kwargs)

    monkeypatch.setattr(
        notification_handler, "send_realtime_notification", _capture
    )

    async def _no_email(**kwargs):
        raise AssertionError("email must not be sent")

    monkeypatch.setattr(notification_email_handler, "send_email", _no_email)

    prefs = NotificationPreference(
        user_id=clinic_a["patient"].id, email_enabled=False,
        realtime_enabled=True,
    )
    db.add(prefs)
    await db.flush()

    await _deliver(
        db, "APPOINTMENT_CONFIRMED",
        _payload(
            "APPOINTMENT_CONFIRMED", appointment=clinic_a["appointment"],
            recipient_id=clinic_a["patient"].id,
        ),
    )

    assert len(realtime) == 1


# ---------------------------------------------------------------------------
# Idempotency and receipts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redelivery_does_not_email_twice(db, clinic_a, sent):
    """The outbox is at-least-once. email_delivered_at is write-once per
    (event_id, user_id), so it is the guard — not the push Redis claim, which
    exists because an ENQUEUE leaves no record."""
    payload = _payload(
        "APPOINTMENT_CONFIRMED", appointment=clinic_a["appointment"],
        recipient_id=clinic_a["patient"].id,
    )

    event = await _deliver(db, "APPOINTMENT_CONFIRMED", payload)

    await handle_event(db, event)
    await handle_event(db, event)

    assert len(sent) == 1, f"redelivery sent {len(sent)} emails"


@pytest.mark.asyncio
async def test_the_receipt_lands_on_the_intended_recipient(db, clinic_a, sent):
    event = await _deliver(
        db, "APPOINTMENT_CONFIRMED",
        _payload(
            "APPOINTMENT_CONFIRMED", appointment=clinic_a["appointment"],
            recipient_id=clinic_a["patient"].id,
        ),
    )

    stored = await db.scalar(
        select(Notification).where(
            Notification.event_id == event.id,
            Notification.user_id == clinic_a["patient"].id,
        )
    )

    assert stored.email_delivered_at is not None
    assert stored.email_failed_at is None


@pytest.mark.asyncio
async def test_a_repeated_receipt_keeps_the_first_timestamp(db, clinic_a, sent):
    from app.services.notification_receipt_service import mark_email_delivered

    event = await _deliver(
        db, "APPOINTMENT_CONFIRMED",
        _payload(
            "APPOINTMENT_CONFIRMED", appointment=clinic_a["appointment"],
            recipient_id=clinic_a["patient"].id,
        ),
    )

    stored = await db.scalar(
        select(Notification).where(Notification.event_id == event.id)
    )
    first = stored.email_delivered_at

    await mark_email_delivered(
        db=db, event_id=event.id, user_id=clinic_a["patient"].id
    )
    await db.refresh(stored)

    assert stored.email_delivered_at == first


@pytest.mark.asyncio
async def test_a_failure_marks_only_the_intended_recipient(
    db, clinic_a, monkeypatch
):
    """One event can carry notifications for two people; a failure must not be
    written onto both."""
    other = await _patient(db, "bystander")

    async def _explode(**kwargs):
        raise RuntimeError("smtp refused")

    monkeypatch.setattr(notification_email_handler, "send_email", _explode)

    payload = _payload(
        "APPOINTMENT_CONFIRMED", appointment=clinic_a["appointment"],
        recipient_id=clinic_a["patient"].id,
    )

    event = OutboxEvent(
        id=uuid.uuid4(), event_type="APPOINTMENT_CONFIRMED",
        payload=payload, status=OutboxStatus.PENDING,
    )
    db.add(event)
    await db.flush()

    # A second notification on the same event, for someone else.
    db.add(Notification(
        user_id=other.id, title="t", message="m",
        category="APPOINTMENT", event_id=event.id,
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

    assert rows[clinic_a["patient"].id].email_failed_at is not None
    assert rows[other.id].email_failed_at is None


@pytest.mark.asyncio
async def test_a_failed_email_can_succeed_on_retry(db, clinic_a, monkeypatch):
    """A failure must not poison the guard: email_delivered_at is still NULL,
    so the redelivery is allowed to try again."""
    attempts = []

    async def _fail_once(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise RuntimeError("smtp refused")

    monkeypatch.setattr(notification_email_handler, "send_email", _fail_once)

    payload = _payload(
        "APPOINTMENT_CONFIRMED", appointment=clinic_a["appointment"],
        recipient_id=clinic_a["patient"].id,
    )

    event = OutboxEvent(
        id=uuid.uuid4(), event_type="APPOINTMENT_CONFIRMED",
        payload=payload, status=OutboxStatus.PENDING,
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

    assert stored.email_delivered_at is not None
    assert stored.email_failed_at is not None, (
        "the earlier failure was erased"
    )


# ---------------------------------------------------------------------------
# The allowlist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type",
    ["APPOINTMENT_STATUS_CHANGED", "CONSULTATION_STARTED",
     "PATIENT_NEXT_IN_QUEUE", "PAYMENT_SUCCESS", "PRESCRIPTION_CREATED"],
)
async def test_events_outside_the_six_send_no_email(
    db, clinic_a, sent, event_type
):
    extra = {
        "APPOINTMENT_STATUS_CHANGED": {"new_status": "CONFIRMED", "doctor_id": 1},
        "CONSULTATION_STARTED": {"doctor_id": 1},
        "PATIENT_NEXT_IN_QUEUE": {"doctor_id": 1},
        "PRESCRIPTION_CREATED": {"prescription_id": 1, "doctor_id": 1},
    }.get(event_type, {})

    await _deliver(
        db, event_type,
        _payload(
            event_type, appointment=clinic_a["appointment"],
            recipient_id=clinic_a["patient"].id, extra=extra,
        ),
    )

    assert sent == [], f"{event_type} is not on the allowlist but sent email"


def test_the_allowlist_is_exactly_the_six_approved_events():
    assert set(EMAIL_EVENTS) == set(SIX)


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------


def test_no_email_template_contains_clinical_content():
    """An inbox is far less private than a logged-in session, so these carry no
    more than the in-app notification already shows."""
    import re
    from pathlib import Path

    banned = re.compile(
        r"medicine|medication|dosage|frequency|diagnos|allerg", re.IGNORECASE
    )

    templates = (
        Path(__file__).parent.parent.parent / "app" / "templates" / "emails"
    )

    offenders = [
        path.name
        for path in templates.glob("*.html")
        if banned.search(path.read_text())
    ]

    assert not offenders, f"clinical content in email templates: {offenders}"


@pytest.mark.asyncio
async def test_the_prescription_revised_email_names_nothing_clinical(
    db, clinic_a, sent
):
    await _deliver(
        db, "PRESCRIPTION_REVISED",
        _payload(
            "PRESCRIPTION_REVISED", appointment=clinic_a["appointment"],
            recipient_id=clinic_a["patient"].id,
            extra=EXTRAS["PRESCRIPTION_REVISED"],
        ),
    )

    body = sent[0]["html_body"] + sent[0]["subject"]

    for forbidden in ("Napa", "Paracetamol", "500mg", "dosage", "diagnosis"):
        assert forbidden.lower() not in body.lower()

    # And no internal identifiers.
    assert str(clinic_a["appointment"].id) not in body


@pytest.mark.asyncio
async def test_templates_render_deterministically(db, clinic_a, sent):
    """Same input, same output — no timestamps, no randomness, no model."""
    payload = _payload(
        "APPOINTMENT_CONFIRMED", appointment=clinic_a["appointment"],
        recipient_id=clinic_a["patient"].id,
    )

    await _deliver(db, "APPOINTMENT_CONFIRMED", payload)

    second = dict(payload)
    second["correlation_id"] = str(uuid.uuid4())
    await _deliver(db, "APPOINTMENT_CONFIRMED", second)

    assert len(sent) == 2
    assert sent[0]["html_body"] == sent[1]["html_body"]
    assert sent[0]["subject"] == sent[1]["subject"]

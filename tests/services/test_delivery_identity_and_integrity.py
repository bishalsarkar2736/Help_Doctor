"""Two things the delivery path got wrong about identity.

A notification is identified by (event_id, user_id) — that is what
uq_notification_event_user says, and it is what lets one event carry a
notification for several people.

The receipt helpers ignored half of it. mark_push_delivered and
mark_delivery_failed matched on event_id alone, so recording one recipient's
outcome rewrote every recipient's row: one patient's phone receiving a push
marked the doctor's notification delivered too.

And the worker ignored the difference between conflicts. Every IntegrityError
was logged as `duplicate_notification_skipped` and swallowed, so a foreign key
violation — a notification pointing at an appointment that does not exist — was
reported as a duplicate and the event vanished: no retry, no dead letter, no
notification, and a log line naming the wrong cause.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError

from app.core.time import utc_now
from app.models.appointment import Appointment, AppointmentStatus
from app.models.clinic import Clinic, ClinicStatus
from app.models.doctor import Doctor, DoctorStatus
from app.models.notification import Notification, NotificationCategory
from app.models.outbox_event import OutboxEvent, OutboxStatus
from app.models.patient import Gender, Patient
from app.models.user import User, UserRole
from app.services.notification_receipt_service import (
    mark_delivery_failed,
    mark_push_delivered,
)
from app.workers.outbox_worker import NonRetryableError, handle_event


@pytest.fixture
async def shared_event(db):
    """One outbox event, two notifications, two different recipients.

    uq_notification_event_user permits exactly this, and it is the arrangement
    the old event_id-only predicate could not tell apart.
    """
    clinic = Clinic(name="Identity Clinic", status=ClinicStatus.ACTIVE, timezone="UTC")
    db.add(clinic)
    await db.flush()

    user_a = User(
        email="identity-a@example.com", full_name="User A", hashed_password="x",
        role=UserRole.PATIENT, is_active=True,
    )
    user_b = User(
        email="identity-b@example.com", full_name="User B", hashed_password="x",
        role=UserRole.DOCTOR, is_active=True, clinic_id=clinic.id,
    )
    db.add_all([user_a, user_b])
    await db.flush()

    event = OutboxEvent(
        id=uuid.uuid4(), event_type="APPOINTMENT_CANCELLED",
        payload={}, status="processed",
    )
    db.add(event)
    await db.flush()

    rows = {}
    for tag, user in (("A", user_a), ("B", user_b)):
        notification = Notification(
            user_id=user.id, title=f"t{tag}", message=f"m{tag}",
            category=NotificationCategory.APPOINTMENT, event_id=event.id,
        )
        db.add(notification)
        rows[tag] = notification

    await db.flush()

    return {"event": event, "A": rows["A"], "B": rows["B"],
            "user_a": user_a, "user_b": user_b}


async def _reload(db, notification):
    await db.refresh(notification)
    return notification


# ---------------------------------------------------------------------------
# Delivery success belongs to one recipient
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_success_marks_only_the_delivered_recipient(db, shared_event):
    """Before: matching on event_id alone marked B delivered as well."""
    await mark_push_delivered(
        db=db,
        event_id=shared_event["event"].id,
        user_id=shared_event["user_a"].id,
    )

    a = await _reload(db, shared_event["A"])
    b = await _reload(db, shared_event["B"])

    assert a.push_delivered_at is not None
    assert a.delivered_at is not None

    assert b.push_delivered_at is None, (
        "the other recipient was marked delivered by someone else's push"
    )
    assert b.delivered_at is None


@pytest.mark.asyncio
async def test_failure_marks_only_the_failed_recipient(db, shared_event):
    await mark_delivery_failed(
        db=db,
        event_id=shared_event["event"].id,
        user_id=shared_event["user_a"].id,
        error="device unreachable",
    )

    a = await _reload(db, shared_event["A"])
    b = await _reload(db, shared_event["B"])

    assert a.delivery_failed_at is not None
    assert a.delivery_error == "device unreachable"

    assert b.delivery_failed_at is None, (
        "the other recipient was marked failed by someone else's failure"
    )
    assert b.delivery_error is None


@pytest.mark.asyncio
async def test_each_recipient_can_have_a_different_outcome(db, shared_event):
    """The case the old predicate made impossible to represent: one push
    landed, the other did not."""
    await mark_push_delivered(
        db=db, event_id=shared_event["event"].id,
        user_id=shared_event["user_a"].id,
    )
    await mark_delivery_failed(
        db=db, event_id=shared_event["event"].id,
        user_id=shared_event["user_b"].id, error="no device token",
    )

    a = await _reload(db, shared_event["A"])
    b = await _reload(db, shared_event["B"])

    assert a.push_delivered_at is not None and a.delivery_failed_at is None
    assert b.delivery_failed_at is not None and b.push_delivered_at is None


# ---------------------------------------------------------------------------
# The ordinary single-recipient case is unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_single_recipient_case_still_works(db, shared_event):
    """Every event in production currently has one recipient, so this is the
    path that must not regress."""
    await mark_push_delivered(
        db=db, event_id=shared_event["event"].id,
        user_id=shared_event["user_a"].id,
    )

    assert (await _reload(db, shared_event["A"])).push_delivered_at is not None


@pytest.mark.asyncio
async def test_repeating_success_is_idempotent(db, shared_event):
    """Write-once: the row keeps the FIRST delivery time rather than drifting
    forward every time the task is redelivered."""
    await mark_push_delivered(
        db=db, event_id=shared_event["event"].id,
        user_id=shared_event["user_a"].id,
    )
    first = (await _reload(db, shared_event["A"])).push_delivered_at

    await mark_push_delivered(
        db=db, event_id=shared_event["event"].id,
        user_id=shared_event["user_a"].id,
    )

    assert (await _reload(db, shared_event["A"])).push_delivered_at == first


@pytest.mark.asyncio
async def test_repeating_failure_keeps_the_first_error(db, shared_event):
    """Later retries of an already-broken delivery report downstream symptoms;
    the first error is the one that explains it."""
    await mark_delivery_failed(
        db=db, event_id=shared_event["event"].id,
        user_id=shared_event["user_a"].id, error="original cause",
    )
    await mark_delivery_failed(
        db=db, event_id=shared_event["event"].id,
        user_id=shared_event["user_a"].id, error="later symptom",
    )

    a = await _reload(db, shared_event["A"])

    assert a.delivery_error == "original cause"


@pytest.mark.asyncio
async def test_a_failure_then_a_success_stays_legible(db, shared_event):
    """Failed then recovered must remain distinguishable from never failed."""
    await mark_delivery_failed(
        db=db, event_id=shared_event["event"].id,
        user_id=shared_event["user_a"].id, error="transient",
    )
    await mark_push_delivered(
        db=db, event_id=shared_event["event"].id,
        user_id=shared_event["user_a"].id,
    )

    a = await _reload(db, shared_event["A"])

    assert a.delivery_failed_at is not None
    assert a.push_delivered_at is not None


@pytest.mark.asyncio
async def test_an_unknown_recipient_changes_nothing(db, shared_event):
    await mark_push_delivered(
        db=db, event_id=shared_event["event"].id, user_id=987654,
    )

    assert (await _reload(db, shared_event["A"])).push_delivered_at is None
    assert (await _reload(db, shared_event["B"])).push_delivered_at is None


# ---------------------------------------------------------------------------
# Integrity errors are classified, not assumed
# ---------------------------------------------------------------------------


@pytest.fixture
async def deliverable(db):
    """A real appointment, so an event can be handled end to end."""
    clinic = Clinic(name="Integrity Clinic", status=ClinicStatus.ACTIVE, timezone="UTC")
    db.add(clinic)
    await db.flush()

    doctor_user = User(
        email="integrity-doc@example.com", full_name="Dr I", hashed_password="x",
        role=UserRole.DOCTOR, is_active=True, clinic_id=clinic.id,
    )
    patient = User(
        email="integrity-pat@example.com", full_name="Patient I",
        hashed_password="x", role=UserRole.PATIENT, is_active=True,
    )
    db.add_all([doctor_user, patient])
    await db.flush()

    doctor = Doctor(
        user_id=doctor_user.id, clinic_id=clinic.id, specialization="Medicine",
        experience_years=1, bio="b", status=DoctorStatus.APPROVED,
    )
    db.add(doctor)

    db.add(Patient(
        user_id=patient.id, phone="+8801966000111", address="a",
        date_of_birth=utc_now().date(), gender=Gender.MALE,
    ))
    await db.flush()

    start = utc_now() + timedelta(days=1)
    appointment = Appointment(
        patient_id=patient.id, doctor_id=doctor.id, clinic_id=clinic.id,
        scheduled_at=start, status=AppointmentStatus.CONFIRMED,
        time_range=Range(start, start + Appointment.APPOINTMENT_DURATION),
    )
    db.add(appointment)
    await db.flush()

    return {"patient": patient, "doctor_user": doctor_user,
            "appointment": appointment}


def _payload(ctx, appointment_id):
    return {
        "event_type": "APPOINTMENT_CANCELLED",
        "schema_version": 1,
        "occurred_at": utc_now().isoformat(),
        "aggregate_type": "appointment",
        "aggregate_id": ctx["appointment"].id,
        "correlation_id": str(uuid.uuid4()),
        "user_id": ctx["patient"].id,
        "appointment_id": appointment_id,
        "cancelled_by": {"id": ctx["doctor_user"].id, "role": "DOCTOR"},
        "reason": "x",
    }


async def _queue(db, ctx, appointment_id):
    event = OutboxEvent(
        id=uuid.uuid4(), event_type="APPOINTMENT_CANCELLED",
        payload=_payload(ctx, appointment_id), status=OutboxStatus.PENDING,
    )
    db.add(event)
    await db.flush()
    return event


class _RecordingLogger:
    """Captures logger calls directly.

    caplog is unreliable here: app.try_except.logging.setup_logging does
    `root.handlers = [handler]`, replacing pytest's capture handler once the
    application has been constructed anywhere in the session. Recording the
    calls is deterministic and does not depend on which tests ran first.
    """

    def __init__(self):
        self.calls = []

    def _record(self, level):
        def capture(message, *args, **kwargs):
            self.calls.append((level, message, kwargs.get("extra") or {}))

        return capture

    def __getattr__(self, level):
        return self._record(level)

    def messages(self):
        return [message for _, message, _ in self.calls]

    def extra_for(self, message):
        return next(e for _, m, e in self.calls if m == message)


@pytest.mark.asyncio
async def test_a_foreign_key_violation_is_not_called_a_duplicate(
    db, deliverable, monkeypatch
):
    """The headline fix.

    An appointment id that does not exist violates
    notifications_related_appointment_id_fkey. That was swallowed as
    `duplicate_notification_skipped` and the event marked processed — the
    notification lost with a log line naming the wrong cause.
    """
    from app.workers import outbox_worker

    recorder = _RecordingLogger()
    monkeypatch.setattr(outbox_worker, "logger", recorder)

    event = await _queue(db, deliverable, appointment_id=987654)

    with pytest.raises(NonRetryableError):
        await handle_event(db, event)

    assert "duplicate_notification_skipped" not in recorder.messages(), (
        "a foreign key violation was still classified as a duplicate"
    )
    assert "outbox_integrity_error" in recorder.messages()

    extra = recorder.extra_for("outbox_integrity_error")

    assert extra["sqlstate"] == "23503"
    assert extra["constraint"] == "notifications_related_appointment_id_fkey"


@pytest.mark.asyncio
async def test_a_foreign_key_violation_reaches_the_dead_letter_path(
    db, deliverable
):
    """NonRetryableError is the route a failed schema validation already takes,
    so this follows the existing convention rather than inventing one: straight
    to the dead letter queue instead of burning five retries on data that
    cannot become valid."""
    event = await _queue(db, deliverable, appointment_id=987654)

    with pytest.raises(NonRetryableError) as raised:
        await handle_event(db, event)

    assert "notifications_related_appointment_id_fkey" in str(raised.value)


@pytest.mark.asyncio
async def test_a_genuine_duplicate_is_still_skipped_quietly(
    db, deliverable, monkeypatch
):
    """The one conflict that is an expected outcome, and the only one still
    swallowed. Deduplication must not be weakened by classifying it."""
    from app.workers import outbox_worker

    recorder = _RecordingLogger()

    event = await _queue(db, deliverable, deliverable["appointment"].id)

    await handle_event(db, event)

    monkeypatch.setattr(outbox_worker, "logger", recorder)

    # A redelivery must not raise, and must still be recognised as a duplicate.
    await handle_event(db, event)

    assert "outbox_integrity_error" not in recorder.messages()

    stored = (
        await db.scalars(
            select(Notification).where(Notification.event_id == event.id)
        )
    ).all()

    assert len(stored) == 1, "redelivery created a second notification"


@pytest.mark.asyncio
async def test_an_unexpected_integrity_error_is_not_swallowed(
    db, deliverable, monkeypatch
):
    """Anything the classifier does not recognise stays observable.

    Re-raised, so it takes the ordinary retry path and ends in the dead letter
    queue if it persists — rather than being marked processed and forgotten.
    """
    from app.services.event_handlers import dispatcher

    async def _raise_unknown(**kwargs):
        raise IntegrityError("stmt", {}, Exception("check constraint blew up"))

    monkeypatch.setattr(dispatcher, "dispatch_event", _raise_unknown)
    monkeypatch.setattr(
        "app.workers.outbox_worker.dispatch_event", _raise_unknown
    )

    event = await _queue(db, deliverable, deliverable["appointment"].id)

    with pytest.raises(IntegrityError):
        await handle_event(db, event)


def test_the_classifier_reads_driver_attributes_not_message_text():
    """SQLSTATE and constraint name come from the driver.

    Matching on the message text would break on a wording or locale change, and
    would be the kind of fix that looks right until Postgres is upgraded.
    """
    from app.workers.outbox_worker import _integrity_details

    class _Cause(Exception):
        sqlstate = "23503"
        constraint_name = "some_fkey"

    class _Orig(Exception):
        pass

    orig = _Orig()
    orig.__cause__ = _Cause()

    exc = IntegrityError("stmt", {}, orig)

    assert _integrity_details(exc) == ("23503", "some_fkey")


def test_an_unrecognisable_error_shape_is_treated_as_unexpected():
    """Reading defensively must fail towards "unexpected", never towards
    "duplicate"."""
    from app.workers.outbox_worker import _integrity_details

    assert _integrity_details(IntegrityError("stmt", {}, Exception("x"))) == (
        None,
        None,
    )

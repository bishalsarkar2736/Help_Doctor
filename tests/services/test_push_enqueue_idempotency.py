"""One push per recipient per event, however many times the event is delivered.

The outbox is at-least-once. task_acks_late means a worker that dies after
delivering redelivers the row, and a handler that raises anywhere after the
notification was written is retried from the top.

The notification RECORD survives that: create_notification uses
ON CONFLICT DO NOTHING over uq_notification_event_user, so a redelivery finds
the existing row. The push did not. notify_user enqueued unconditionally,
without asking whether the row it just "created" was new, so every redelivery
sent the device another copy of a notification the user already had.

The record was deduplicated and the delivery was not, which is the failure mode
worth naming: the database looked correct while the phone buzzed three times.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import Range

from app.core.time import utc_now
from app.models.appointment import Appointment, AppointmentStatus
from app.models.clinic import Clinic, ClinicStatus
from app.models.doctor import Doctor, DoctorStatus
from app.models.notification import Notification
from app.models.outbox_event import OutboxEvent, OutboxStatus
from app.models.patient import Gender, Patient
from app.models.user import User, UserRole
from app.task.notification_tasks import send_push_notification_task
from app.workers.outbox_worker import handle_event


@pytest.fixture
def enqueued(monkeypatch):
    """Every push enqueue, recorded instead of sent.

    Patched on the task object so it is caught wherever it is called from —
    notification_service imports the task by name at module scope.
    """
    calls = []

    def _record(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(send_push_notification_task, "delay", _record)

    return calls


@pytest.fixture
async def clinic_ctx(db):
    clinic = Clinic(name="Push Clinic", status=ClinicStatus.ACTIVE, timezone="UTC")
    db.add(clinic)
    await db.flush()

    doctor_user = User(
        email="push-doc@example.com", full_name="Dr Push", hashed_password="x",
        role=UserRole.DOCTOR, is_active=True, clinic_id=clinic.id,
    )
    patient_user = User(
        email="push-pat@example.com", full_name="Push Patient",
        hashed_password="x", role=UserRole.PATIENT, is_active=True,
    )
    db.add_all([doctor_user, patient_user])
    await db.flush()

    doctor = Doctor(
        user_id=doctor_user.id, clinic_id=clinic.id, specialization="Medicine",
        experience_years=1, bio="b", status=DoctorStatus.APPROVED,
    )
    db.add(doctor)

    db.add(Patient(
        user_id=patient_user.id, phone="+8801977000111", address="a",
        date_of_birth=utc_now().date(), gender=Gender.MALE,
    ))
    await db.flush()

    start = utc_now() + timedelta(days=1)
    appointment = Appointment(
        patient_id=patient_user.id, doctor_id=doctor.id, clinic_id=clinic.id,
        scheduled_at=start, status=AppointmentStatus.CONFIRMED,
        time_range=Range(start, start + Appointment.APPOINTMENT_DURATION),
    )
    db.add(appointment)
    await db.flush()

    return {
        "clinic": clinic,
        "doctor_user": doctor_user,
        "patient": patient_user,
        "appointment": appointment,
    }


async def _queue_event(db, ctx, recipient_id):
    """One outbox row addressed to a party of the appointment."""
    event = OutboxEvent(
        id=uuid.uuid4(),
        event_type="APPOINTMENT_CANCELLED",
        payload={
            "event_type": "APPOINTMENT_CANCELLED",
            "schema_version": 1,
            "occurred_at": utc_now().isoformat(),
            "aggregate_type": "appointment",
            "aggregate_id": ctx["appointment"].id,
            "correlation_id": str(uuid.uuid4()),
            "user_id": recipient_id,
            "appointment_id": ctx["appointment"].id,
            "cancelled_by": {"id": ctx["doctor_user"].id, "role": "DOCTOR"},
            "reason": "clinic closed",
        },
        status=OutboxStatus.PENDING,
    )
    db.add(event)
    await db.flush()
    return event


def _pushes_for(calls, user_id):
    return [c for c in calls if c.get("user_id") == user_id]


# ---------------------------------------------------------------------------
# The failure this exists to fix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redelivery_enqueues_exactly_one_push(db, clinic_ctx, enqueued):
    """Three deliveries of one event, one push.

    Before the guard this enqueued three: create_notification returned the
    existing row on the second and third passes and notify_user enqueued
    anyway.
    """
    event = await _queue_event(db, clinic_ctx, clinic_ctx["patient"].id)

    await handle_event(db, event)
    await handle_event(db, event)
    await handle_event(db, event)

    assert len(_pushes_for(enqueued, clinic_ctx["patient"].id)) == 1, (
        f"redelivery enqueued {len(enqueued)} pushes for one notification"
    )


@pytest.mark.asyncio
async def test_the_record_is_still_deduplicated_too(db, clinic_ctx, enqueued):
    """The half that already worked must keep working — the guard must not be
    achieving its count by suppressing the row."""
    event = await _queue_event(db, clinic_ctx, clinic_ctx["patient"].id)

    await handle_event(db, event)
    await handle_event(db, event)

    assert await db.scalar(
        select(func.count(Notification.id)).where(
            Notification.event_id == event.id
        )
    ) == 1


# ---------------------------------------------------------------------------
# What must NOT be suppressed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_recipients_of_one_event_each_get_a_push(
    db, clinic_ctx, enqueued
):
    """The key has to be (event_id, user_id), not event_id.

    uq_notification_event_user permits two users on one event, so a guard keyed
    on the event alone would silence the second recipient — trading a duplicate
    push for a missing one.
    """
    event = await _queue_event(db, clinic_ctx, clinic_ctx["patient"].id)

    await handle_event(db, event)

    # The same event delivered to the other party to the appointment.
    event.payload = {**event.payload, "user_id": clinic_ctx["doctor_user"].id}
    await db.flush()

    await handle_event(db, event)

    assert len(_pushes_for(enqueued, clinic_ctx["patient"].id)) == 1
    assert len(_pushes_for(enqueued, clinic_ctx["doctor_user"].id)) == 1


@pytest.mark.asyncio
async def test_separate_events_to_one_user_each_get_a_push(
    db, clinic_ctx, enqueued
):
    """Two genuine notifications are two pushes. The guard is per event, not
    per user — a user must not go quiet after their first notification."""
    first = await _queue_event(db, clinic_ctx, clinic_ctx["patient"].id)
    second = await _queue_event(db, clinic_ctx, clinic_ctx["patient"].id)

    await handle_event(db, first)
    await handle_event(db, second)

    assert len(_pushes_for(enqueued, clinic_ctx["patient"].id)) == 2


@pytest.mark.asyncio
async def test_the_celery_task_still_retries_a_failed_send(db, clinic_ctx):
    """Idempotency is about ENQUEUE, not about delivery.

    Once the task is running, a genuine send failure must still retry — that is
    the task's own autoretry and this change must not reach it.
    """
    assert send_push_notification_task.max_retries == 5
    assert send_push_notification_task.autoretry_for == (Exception,)


@pytest.mark.asyncio
async def test_a_failed_push_is_distinguishable_from_a_delivered_one(
    db, clinic_ctx, enqueued
):
    """The record keeps the two apart, and the guard does not blur them.

    delivery_failed_at and push_delivered_at are separate columns; suppressing
    a duplicate enqueue must not leave a notification that looks delivered when
    it never was.
    """
    event = await _queue_event(db, clinic_ctx, clinic_ctx["patient"].id)

    await handle_event(db, event)

    stored = await db.scalar(
        select(Notification).where(Notification.event_id == event.id)
    )

    # Enqueued, not yet run: neither delivered nor failed.
    assert stored.push_delivered_at is None
    assert stored.delivery_failed_at is None


# ---------------------------------------------------------------------------
# The guard must not become a new way to lose notifications
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_enqueue_can_be_retried(db, clinic_ctx, monkeypatch):
    """The claim is only meaningful once the task is actually queued.

    If the broker is briefly down, the claim is handed back — otherwise the
    redelivery that exists to recover the push would see it already taken and
    skip, turning a transient failure into a notification nobody ever gets.
    """
    attempts = []

    def _broker_down(**kwargs):
        attempts.append(kwargs)
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(send_push_notification_task, "delay", _broker_down)

    event = await _queue_event(db, clinic_ctx, clinic_ctx["patient"].id)

    await handle_event(db, event)

    assert len(attempts) == 1, "the first delivery did not attempt an enqueue"

    # Broker recovers; the redelivery must be allowed to try again.
    succeeded = []
    monkeypatch.setattr(
        send_push_notification_task, "delay", lambda **kw: succeeded.append(kw)
    )

    await handle_event(db, event)

    assert len(succeeded) == 1, (
        "the claim was not released, so the retry that should have recovered "
        "the push was suppressed"
    )


@pytest.mark.asyncio
async def test_the_guard_fails_open_when_redis_is_unreachable(
    db, clinic_ctx, enqueued, monkeypatch
):
    """A duplicate push is a nuisance. A Redis outage silently suppressing
    every notification is an incident.

    The guard exists to remove an annoyance and must not become a new single
    point of failure.
    """
    from app.services import notification_service

    async def _redis_down():
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(notification_service, "get_redis", _redis_down)

    event = await _queue_event(db, clinic_ctx, clinic_ctx["patient"].id)

    await handle_event(db, event)

    assert len(_pushes_for(enqueued, clinic_ctx["patient"].id)) == 1, (
        "the push was suppressed because the guard could not be consulted"
    )

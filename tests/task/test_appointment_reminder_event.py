"""The appointment reminder, from the scheduled job to the patient's phone.

WHAT WAS BROKEN
The job ran every 60 seconds and published, for each due appointment, an
OutboxEvent with event_type="appointment.reminder". The worker upper-cases the
type and looks it up in EVENT_SCHEMAS, where "APPOINTMENT.REMINDER" does not
appear — so it logged skipping_unsupported_event, set status="processed" and
returned. No error, no dead letter, nothing delivered.

And the same transaction had already set appointment.reminder_sent = True, so the
appointment was permanently marked as reminded. The reminder was not delayed or
retried; it was consumed. Every reminder this platform has ever "sent" was lost
this way.

It also built the OutboxEvent by hand, bypassing publish_domain_event — the
single publisher every other event in the system goes through. That is why the
type could be a string nobody validated: nothing in the informal path checked it
against the registry.

WHAT IS ASSERTED HERE
That the event is registered, published through the one publisher, validates
against its schema, is routed to the patient channels, and survives the worker as
a real notification rather than a skipped row. Then the WhatsApp message itself:
doctor, date and time, in the clinic's timezone, subject to every existing gate.

And the flag: an appointment must not be marked reminded unless its event was
actually published.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

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
from app.schemas.event import AppointmentReminderEvent
from app.schemas.event_registry import EVENT_SCHEMAS
from app.services.event_handlers import notification_whatsapp_handler
from app.task import appointment_reminders
from app.task.appointment_reminders import (
    REMINDER_CATCHUP_MINUTES,
    REMINDER_LEAD_MINUTES,
)
from app.workers.outbox_worker import handle_event

EVENT_TYPE = "APPOINTMENT_REMINDER"

TEMPLATE = "helpdoctor_appointment_reminder"

# Inside the reminder band, so the job's own query selects it. Half an hour used
# to qualify; the reminder now goes out about a day ahead, because the approved
# message says "tomorrow".
DUE_IN = timedelta(minutes=REMINDER_LEAD_MINUTES - 30)


def _use_test_session(db):
    """Point the job's AsyncSessionLocal at the test session.

    The job opens its own session, which would otherwise be the dev database.
    Same approach as tests/task/test_notification_push_task.py.
    """

    @asynccontextmanager
    async def _cm():
        yield db

    return patch.object(
        appointment_reminders, "AsyncSessionLocal", lambda: _cm()
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _clinic(db, tag: str, *, timezone: str = "UTC") -> dict:
    clinic = Clinic(
        name=f"Reminder {tag}", status=ClinicStatus.ACTIVE, timezone=timezone
    )
    db.add(clinic)
    await db.flush()

    doctor_user = User(
        email=f"rem-doc-{tag}@example.com", full_name="Rahman",
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


async def _patient(db, tag: str, *, phone="+8801955000111") -> User:
    user = User(
        email=f"rem-pat-{tag}@example.com", full_name=f"Patient {tag}",
        hashed_password="x", role=UserRole.PATIENT, is_active=True,
    )
    db.add(user)
    await db.flush()

    db.add(Patient(
        user_id=user.id, phone=phone, address="a",
        date_of_birth=utc_now().date(), gender=Gender.MALE,
    ))

    # WhatsApp is opt-in, so every test patient opts in. Without this the
    # "nothing was sent" assertions below would hold for the wrong reason.
    db.add(NotificationPreference(user_id=user.id, whatsapp_enabled=True))

    await db.flush()

    return user


async def _appointment(
    db, ctx, patient, *, due_in=DUE_IN, at=None,
    status=AppointmentStatus.CONFIRMED,
) -> Appointment:
    start = at or (utc_now() + due_in)

    appointment = Appointment(
        patient_id=patient.id, doctor_id=ctx["doctor"].id,
        clinic_id=ctx["clinic"].id, scheduled_at=start, status=status,
        time_range=Range(start, start + Appointment.APPOINTMENT_DURATION),
    )
    db.add(appointment)
    await db.flush()

    return appointment


@pytest.fixture
async def due(db):
    """One clinic, one patient, one appointment due inside the window."""
    ctx = await _clinic(db, "A")
    ctx["patient"] = await _patient(db, "a")
    ctx["appointment"] = await _appointment(db, ctx, ctx["patient"])
    return ctx


@pytest.fixture
def channel_on(monkeypatch):
    settings = get_settings()

    monkeypatch.setattr(settings, "WHATSAPP_NOTIFICATIONS_ENABLED", True)
    monkeypatch.setattr(
        settings, "WHATSAPP_TEMPLATE_APPOINTMENT_REMINDER", TEMPLATE
    )

    return settings


@pytest.fixture
def sent(monkeypatch):
    messages = []

    async def _capture(**kwargs):
        messages.append(kwargs)
        return {}

    monkeypatch.setattr(
        notification_whatsapp_handler.WhatsAppService, "send_template", _capture
    )

    return messages


def _event_for(appointment, patient) -> OutboxEvent:
    """The event the job would publish, for tests that start after publication."""
    return OutboxEvent(
        id=uuid.uuid4(),
        event_type=EVENT_TYPE,
        status=OutboxStatus.PENDING,
        payload={
            "event_type": EVENT_TYPE,
            "schema_version": 1,
            "occurred_at": utc_now().isoformat(),
            "aggregate_type": "appointment",
            "aggregate_id": appointment.id,
            "correlation_id": str(uuid.uuid4()),
            "user_id": patient.id,
            "appointment_id": appointment.id,
        },
    )


async def _deliver(db, appointment, patient) -> OutboxEvent:
    event = _event_for(appointment, patient)
    db.add(event)
    await db.flush()

    await handle_event(db, event)

    return event


# ---------------------------------------------------------------------------
# The event is a registered domain event
# ---------------------------------------------------------------------------


def test_the_reminder_event_is_registered():
    """The whole bug in one assertion: the worker validates against this map,
    and the reminder was not in it."""
    assert EVENT_SCHEMAS.get(EVENT_TYPE) is AppointmentReminderEvent


def test_the_old_untyped_name_would_still_be_unsupported():
    """Pinned so the fix cannot be misread as "the worker now accepts anything".

    The old value normalises to APPOINTMENT.REMINDER, which must remain
    unregistered — the fix is that the job publishes a registered type, not that
    unregistered types became acceptable.
    """
    assert "appointment.reminder".upper() not in EVENT_SCHEMAS


def test_the_job_no_longer_names_the_event_by_hand():
    """Parsed from the source, because the defect was a string literal.

    The docstring of this module quotes the old name deliberately, so this looks
    at the task module rather than grepping the test suite.
    """
    source = (
        __import__("pathlib").Path(appointment_reminders.__file__).read_text()
    )

    # The literal may survive in a comment explaining the fix; what must not
    # survive is an OutboxEvent built here instead of published.
    assert "OutboxEvent(" not in source, (
        "the job builds an outbox event by hand instead of publishing one"
    )


def test_the_reminder_is_routed_to_the_patient_channels():
    from app.services.event_handlers.dispatcher import (
        EVENT_HANDLERS,
        _with_patient_channels,
    )

    assert EVENT_HANDLERS.get(EVENT_TYPE) is _with_patient_channels


def test_the_reminder_has_a_notification_config():
    """Not decoration: the in-app notification is the row whatsapp_delivered_at
    is written on, so without this entry the channel has nowhere to record a
    delivery and idempotency would have nothing to read."""
    from app.services.event_handlers.notification_handler import (
        EVENT_NOTIFICATION_CONFIG,
    )

    config = EVENT_NOTIFICATION_CONFIG.get(EVENT_TYPE)

    assert config is not None
    assert config["user_field"] == "user_id"
    assert config["appointment_field"] == "appointment_id"


def test_the_reminder_event_defaults_to_user_initiated():
    """A scheduled job publishes it, but it must NOT be SYSTEM.

    SYSTEM suppresses the in-app notification, and that notification is the
    receipt row. A SYSTEM reminder would therefore deliver nothing and record
    nothing — and a reminder is the one scheduled thing whose entire purpose is
    to tell the patient personally.
    """
    from app.schemas.event_metadata import EventSource

    event = AppointmentReminderEvent(
        event_type=EVENT_TYPE,
        occurred_at=utc_now().isoformat(),
        aggregate_type="appointment",
        aggregate_id=1,
        user_id=2,
        appointment_id=1,
    )

    assert event.source is EventSource.USER


# ---------------------------------------------------------------------------
# The job publishes it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_job_publishes_a_reminder_to_the_outbox(db, due):
    with _use_test_session(db):
        await appointment_reminders.send_appointment_reminders()

    events = (
        await db.execute(
            select(OutboxEvent).where(OutboxEvent.event_type == EVENT_TYPE)
        )
    ).scalars().all()

    assert len(events) == 1

    payload = events[0].payload

    assert payload["appointment_id"] == due["appointment"].id
    assert payload["user_id"] == due["patient"].id


@pytest.mark.asyncio
async def test_the_published_event_validates_against_its_schema(db, due):
    """What the worker does before dispatching. A payload that fails here is a
    dead letter, which is the other way this could have silently not worked."""
    with _use_test_session(db):
        await appointment_reminders.send_appointment_reminders()

    event = await db.scalar(
        select(OutboxEvent).where(OutboxEvent.event_type == EVENT_TYPE)
    )

    validated = EVENT_SCHEMAS[EVENT_TYPE].model_validate(event.payload)

    assert validated.appointment_id == due["appointment"].id


@pytest.mark.asyncio
async def test_the_worker_processes_it_instead_of_skipping_it(db, due):
    """The end of the original bug.

    status becoming "processed" is NOT the assertion — that is exactly what the
    broken version did. What proves delivery happened is the notification row.
    """
    with _use_test_session(db):
        await appointment_reminders.send_appointment_reminders()

    event = await db.scalar(
        select(OutboxEvent).where(OutboxEvent.event_type == EVENT_TYPE)
    )

    await handle_event(db, event)

    notification = await db.scalar(
        select(Notification).where(
            Notification.event_id == event.id,
            Notification.user_id == due["patient"].id,
        )
    )

    assert notification is not None, (
        "the reminder was processed without notifying anyone"
    )


@pytest.mark.asyncio
async def test_the_appointment_is_marked_reminded(db, due):
    with _use_test_session(db):
        await appointment_reminders.send_appointment_reminders()

    await db.refresh(due["appointment"])

    assert due["appointment"].reminder_sent is True


@pytest.mark.asyncio
async def test_a_second_run_publishes_nothing_more(db, due):
    for _ in range(2):
        with _use_test_session(db):
            await appointment_reminders.send_appointment_reminders()

    events = (
        await db.execute(
            select(OutboxEvent).where(OutboxEvent.event_type == EVENT_TYPE)
        )
    ).scalars().all()

    assert len(events) == 1


@pytest.mark.asyncio
async def test_the_reminder_is_not_consumed_when_publication_fails(db, due):
    """The flag must not outlive a failed publish.

    This is the property that turned a wiring bug into permanent data loss: the
    old code set reminder_sent alongside an event nothing could process, so the
    appointment was marked reminded forever. Here publication fails outright, and
    the appointment has to remain due.
    """
    async def _boom(**kwargs):
        raise RuntimeError("outbox is unavailable")

    # Committed first, so the appointment is as durable as it is in production.
    # Without this the job's rollback would discard the fixture's own rows and
    # the assertion below would be about the test setup rather than the flag.
    appointment_id = due["appointment"].id
    await db.commit()

    with _use_test_session(db):
        with patch.object(
            appointment_reminders, "publish_domain_event", _boom
        ):
            with pytest.raises(RuntimeError):
                await appointment_reminders.send_appointment_reminders()

    reminded = await db.scalar(
        select(Appointment.reminder_sent).where(
            Appointment.id == appointment_id
        )
    )

    assert reminded is False, (
        "the reminder was consumed although nothing was published"
    )

    events = (
        await db.execute(
            select(OutboxEvent).where(OutboxEvent.event_type == EVENT_TYPE)
        )
    ).scalars().all()

    assert events == []


@pytest.mark.asyncio
async def test_appointments_outside_the_window_are_left_alone(db):
    """Too far away: above the band, so it waits for a later run."""
    ctx = await _clinic(db, "far")
    patient = await _patient(db, "far", phone="+8801955000222")
    appointment = await _appointment(
        db, ctx, patient, due_in=timedelta(days=3)
    )

    with _use_test_session(db):
        await appointment_reminders.send_appointment_reminders()

    await db.refresh(appointment)

    assert appointment.reminder_sent is False


@pytest.mark.asyncio
async def test_unconfirmed_appointments_are_not_reminded(db):
    ctx = await _clinic(db, "pending")
    patient = await _patient(db, "pending", phone="+8801955000333")
    appointment = await _appointment(
        db, ctx, patient, status=AppointmentStatus.PENDING
    )

    with _use_test_session(db):
        await appointment_reminders.send_appointment_reminders()

    await db.refresh(appointment)

    assert appointment.reminder_sent is False


# ---------------------------------------------------------------------------
# The WhatsApp message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_patient_receives_the_reminder(db, due, channel_on, sent):
    await _deliver(db, due["appointment"], due["patient"])

    assert len(sent) == 1
    assert sent[0]["template_name"] == TEMPLATE
    assert sent[0]["phone"] == "+8801955000111"

    doctor, date, time = sent[0]["body_parameters"]

    assert doctor == "Dr. Rahman"
    assert date and time


@pytest.mark.asyncio
async def test_the_reminder_uses_the_clinics_timezone(db, channel_on, sent):
    """20:00 UTC on 15 December is 02:00 on the 16th in Dhaka, so a handler that
    skipped the conversion would get the DATE wrong as well as the time."""
    ctx = await _clinic(db, "dhaka", timezone="Asia/Dhaka")
    patient = await _patient(db, "dhaka", phone="+8801955000444")
    appointment = await _appointment(
        db, ctx, patient, at=datetime(2026, 12, 15, 20, 0, tzinfo=UTC)
    )

    await _deliver(db, appointment, patient)

    assert sent[0]["body_parameters"] == ["Dr. Rahman", "16 December", "02:00 AM"]


@pytest.mark.asyncio
async def test_the_parameters_are_doctor_then_date_then_time(
    db, due, channel_on, sent
):
    """Order is the contract: Meta fills {{1}}, {{2}}, {{3}} positionally, so a
    swap silently puts a time under "Doctor:"."""
    await _deliver(db, due["appointment"], due["patient"])

    doctor, date, time = sent[0]["body_parameters"]

    assert doctor.startswith("Dr.")
    assert time.endswith(("AM", "PM"))
    assert date not in (doctor, time)


@pytest.mark.asyncio
async def test_a_doctor_who_already_has_a_title_is_not_prefixed_twice(
    db, channel_on, sent
):
    ctx = await _clinic(db, "titled")
    ctx["doctor_user"].full_name = "Dr. Karim"
    await db.flush()

    patient = await _patient(db, "titled", phone="+8801955000555")
    appointment = await _appointment(db, ctx, patient)

    await _deliver(db, appointment, patient)

    assert sent[0]["body_parameters"][0] == "Dr. Karim"


@pytest.mark.asyncio
async def test_a_doctor_without_a_name_falls_back_to_a_role(
    db, channel_on, sent
):
    """Never an id, and never an empty slot in the middle of a sentence."""
    ctx = await _clinic(db, "nameless")
    ctx["doctor_user"].full_name = ""
    await db.flush()

    patient = await _patient(db, "nameless", phone="+8801955000666")
    appointment = await _appointment(db, ctx, patient)

    await _deliver(db, appointment, patient)

    assert sent[0]["body_parameters"][0] == "your doctor"


@pytest.mark.asyncio
async def test_no_internal_id_reaches_the_reminder(db, due, channel_on, sent):
    await _deliver(db, due["appointment"], due["patient"])

    forbidden = {
        str(due["appointment"].id),
        str(due["patient"].id),
        str(due["doctor"].id),
        str(due["clinic"].id),
        str(due["doctor_user"].id),
    }

    for value in sent[0]["body_parameters"]:
        assert value not in forbidden


@pytest.mark.asyncio
async def test_no_clinical_information_reaches_the_reminder(
    db, due, channel_on, sent
):
    """Three parameters, all of them scheduling facts. Specialization is on the
    doctor row and within easy reach of a careless parameter list."""
    await _deliver(db, due["appointment"], due["patient"])

    emitted = str(sent[0])

    assert "Medicine" not in emitted
    assert len(sent[0]["body_parameters"]) == 3


@pytest.mark.asyncio
async def test_no_provider_credential_reaches_the_reminder(
    db, due, channel_on, sent
):
    settings = get_settings()

    await _deliver(db, due["appointment"], due["patient"])

    emitted = str(sent[0])

    assert settings.WHATSAPP_ACCESS_TOKEN not in emitted
    assert settings.WHATSAPP_PHONE_NUMBER_ID not in emitted


# ---------------------------------------------------------------------------
# The gates, for this event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_another_clinics_patient_cannot_receive_the_reminder(
    db, due, channel_on, sent
):
    """Refused by the existing recipient validation, non-retryably. Not by a
    clinic-id comparison, which would be meaningless for a global patient."""
    from app.services.event_handlers.notification_handler import (
        RecipientNotPartyToEvent,
    )

    other = await _clinic(db, "B")
    outsider = await _patient(db, "b", phone="+8801955000777")
    await _appointment(db, other, outsider, due_in=timedelta(minutes=45))

    event = _event_for(due["appointment"], outsider)
    db.add(event)
    await db.flush()

    with pytest.raises(RecipientNotPartyToEvent):
        await handle_event(db, event)

    assert sent == []


@pytest.mark.asyncio
async def test_the_kill_switch_stops_the_reminder(
    db, due, channel_on, sent, monkeypatch
):
    monkeypatch.setattr(channel_on, "WHATSAPP_NOTIFICATIONS_ENABLED", False)

    await _deliver(db, due["appointment"], due["patient"])

    assert sent == []


@pytest.mark.asyncio
async def test_an_unapproved_template_stops_the_reminder(
    db, due, channel_on, sent, monkeypatch
):
    monkeypatch.setattr(
        channel_on, "WHATSAPP_TEMPLATE_APPOINTMENT_REMINDER", ""
    )

    await _deliver(db, due["appointment"], due["patient"])

    assert sent == []


@pytest.mark.asyncio
async def test_a_disabled_preference_stops_the_reminder(
    db, due, channel_on, sent
):
    prefs = await db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == due["patient"].id
        )
    )
    prefs.whatsapp_enabled = False
    await db.flush()

    await _deliver(db, due["appointment"], due["patient"])

    assert sent == []


@pytest.mark.asyncio
async def test_a_patient_without_a_phone_is_skipped(db, channel_on, sent):
    ctx = await _clinic(db, "nophone")
    patient = await _patient(db, "nophone", phone="")
    appointment = await _appointment(db, ctx, patient)

    await _deliver(db, appointment, patient)

    assert sent == []


# ---------------------------------------------------------------------------
# Delivery, idempotency and retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delivery_is_recorded_against_the_patient(
    db, due, channel_on, sent
):
    event = await _deliver(db, due["appointment"], due["patient"])

    stored = await db.scalar(
        select(Notification).where(
            Notification.event_id == event.id,
            Notification.user_id == due["patient"].id,
        )
    )

    assert stored.whatsapp_delivered_at is not None


@pytest.mark.asyncio
async def test_a_redelivered_reminder_is_not_sent_twice(
    db, due, channel_on, sent
):
    event = await _deliver(db, due["appointment"], due["patient"])

    await handle_event(db, event)
    await handle_event(db, event)

    assert len(sent) == 1


@pytest.mark.asyncio
async def test_a_failed_reminder_retries_and_then_succeeds(
    db, due, channel_on, monkeypatch
):
    async def _fail(**kwargs):
        raise RuntimeError("meta is down")

    monkeypatch.setattr(
        notification_whatsapp_handler.WhatsAppService, "send_template", _fail
    )

    event = _event_for(due["appointment"], due["patient"])
    db.add(event)
    await db.flush()

    with pytest.raises(RuntimeError):
        await handle_event(db, event)

    stored = await db.scalar(
        select(Notification).where(
            Notification.event_id == event.id,
            Notification.user_id == due["patient"].id,
        )
    )

    assert stored.whatsapp_delivered_at is None
    assert stored.whatsapp_failed_at is not None

    # Nothing recorded a delivery, so the retry is free to send.
    ok = []

    async def _ok(**kwargs):
        ok.append(kwargs)
        return {}

    monkeypatch.setattr(
        notification_whatsapp_handler.WhatsAppService, "send_template", _ok
    )

    await handle_event(db, event)

    assert len(ok) == 1

    await db.refresh(stored)

    assert stored.whatsapp_delivered_at is not None


def test_the_flag_is_written_after_the_publish():
    """The ordering inside the loop, asserted on the code.

    Not a behavioural test, deliberately, and worth saying why. Today the flag
    cannot outlive a failed publish whichever order these two lines are in,
    because the failure unwinds the whole transaction — the test above proves
    that, and swapping the lines does not break it.

    The ordering matters for the shape this loop tends to grow into: a
    per-appointment try/except that logs one failure and carries on with the
    batch. That change would stop the transaction unwinding, and the ordering
    would become the only thing preventing a published-nothing appointment from
    being marked reminded forever. So it is pinned here rather than left as a
    comment that a refactor can quietly invalidate.
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path(appointment_reminders.__file__).read_text())

    loops = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.For)
        and isinstance(node.target, ast.Name)
        and node.target.id == "appointment"
    ]

    assert len(loops) == 1, "expected exactly one per-appointment loop"

    publish_at = None
    flag_at = None

    for index, statement in enumerate(loops[0].body):
        source = ast.dump(statement)

        if "publish_domain_event" in source and publish_at is None:
            publish_at = index

        if "reminder_sent" in source and flag_at is None:
            flag_at = index

    assert publish_at is not None, "the loop does not publish an event"
    assert flag_at is not None, "the loop does not set reminder_sent"

    assert publish_at < flag_at, (
        "reminder_sent is written before the event is published"
    )


# ---------------------------------------------------------------------------
# Timing: the reminder goes out about a day ahead, not about an hour ahead
# ---------------------------------------------------------------------------
#
# The job used to select everything scheduled between now and now + 60 minutes,
# while the approved template said "You have an appointment tomorrow". It now
# selects a BAND ending at the 24-hour mark.
#
# The band matters more than the number. Reading a 24-hour lead time as "within
# the next 24 hours" is the obvious change to make and it is wrong: an
# appointment booked for this afternoon is within 24 hours, so it would be told
# it is tomorrow. The tests below pin both ends.


def test_the_lead_time_is_about_a_day():
    """Pinned as a value, because it is what makes the message true."""
    assert REMINDER_LEAD_MINUTES == 24 * 60


def test_the_band_is_wider_than_the_interval_between_runs():
    """Otherwise an appointment can step over the band while the worker is busy
    or restarting, and never be reminded at all.

    Read from the live beat schedule rather than assumed, so changing the
    schedule without widening the band fails here.
    """
    from app.core.celery import celery_app

    interval = celery_app.conf.beat_schedule["appointment-reminder-job"][
        "schedule"
    ]

    assert REMINDER_CATCHUP_MINUTES * 60 >= interval


@pytest.mark.asyncio
async def test_an_appointment_about_a_day_away_qualifies(db):
    ctx = await _clinic(db, "day")
    patient = await _patient(db, "day", phone="+8801955001111")
    appointment = await _appointment(
        db, ctx, patient, due_in=timedelta(hours=23, minutes=45)
    )

    with _use_test_session(db):
        await appointment_reminders.send_appointment_reminders()

    await db.refresh(appointment)

    assert appointment.reminder_sent is True


@pytest.mark.asyncio
async def test_an_appointment_about_an_hour_away_does_not_qualify(db):
    """The old behaviour, now explicitly excluded.

    An appointment an hour away is not tomorrow. Under the previous window this
    was the ONLY thing that qualified, so this test is the direct inverse of what
    the job used to do — and it is what a naive "within 24 hours" reading would
    get wrong.
    """
    ctx = await _clinic(db, "hour")
    patient = await _patient(db, "hour", phone="+8801955002222")
    appointment = await _appointment(db, ctx, patient, due_in=timedelta(hours=1))

    with _use_test_session(db):
        await appointment_reminders.send_appointment_reminders()

    await db.refresh(appointment)

    assert appointment.reminder_sent is False, (
        "an appointment an hour away was told it is tomorrow"
    )


@pytest.mark.asyncio
async def test_an_appointment_later_today_does_not_qualify(db):
    """Between the two bounds — inside 24 hours, but well below the band."""
    ctx = await _clinic(db, "today")
    patient = await _patient(db, "today", phone="+8801955003333")
    appointment = await _appointment(db, ctx, patient, due_in=timedelta(hours=8))

    with _use_test_session(db):
        await appointment_reminders.send_appointment_reminders()

    await db.refresh(appointment)

    assert appointment.reminder_sent is False


@pytest.mark.asyncio
async def test_an_appointment_beyond_the_band_does_not_qualify_yet(db):
    """Above the band. Not skipped — it qualifies on a later run, once time has
    advanced far enough to bring it inside."""
    ctx = await _clinic(db, "beyond")
    patient = await _patient(db, "beyond", phone="+8801955004444")
    appointment = await _appointment(
        db, ctx, patient, due_in=timedelta(hours=26)
    )

    with _use_test_session(db):
        await appointment_reminders.send_appointment_reminders()

    await db.refresh(appointment)

    assert appointment.reminder_sent is False


@pytest.mark.asyncio
async def test_an_appointment_already_past_does_not_qualify(db):
    """The old query needed an explicit `>= now` for this. The new lower bound is
    nearly a day in the future, so a past appointment cannot be selected — but it
    is asserted rather than assumed, since the guard was removed."""
    ctx = await _clinic(db, "past")
    patient = await _patient(db, "past", phone="+8801955005555")
    appointment = await _appointment(
        db, ctx, patient, due_in=timedelta(hours=-3)
    )

    with _use_test_session(db):
        await appointment_reminders.send_appointment_reminders()

    await db.refresh(appointment)

    assert appointment.reminder_sent is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("offset", "qualifies"),
    [
        (timedelta(minutes=30), False),
        (timedelta(hours=8), False),
        (timedelta(hours=22, minutes=30), False),
        (timedelta(hours=23, minutes=30), True),
        (timedelta(hours=24), True),
        (timedelta(hours=25), False),
        (timedelta(days=2), False),
    ],
)
async def test_the_band_boundaries(db, offset, qualifies):
    """The whole shape in one table, so a change to either bound is visible.

    23h30m and 24h are in; 22h30m and 25h are out. A window running from `now`
    would pass the two "in" rows and fail all four "out" rows below the band,
    which is exactly the mistake this table exists to catch.
    """
    tag = f"band-{int(offset.total_seconds())}"

    ctx = await _clinic(db, tag)
    patient = await _patient(db, tag, phone="+880195500{}".format(
        abs(int(offset.total_seconds())) % 10000
    ))
    appointment = await _appointment(db, ctx, patient, due_in=offset)

    with _use_test_session(db):
        await appointment_reminders.send_appointment_reminders()

    await db.refresh(appointment)

    assert appointment.reminder_sent is qualifies


@pytest.mark.asyncio
async def test_the_reminder_is_still_addressed_to_the_patient(db):
    """The timing changed; the recipient did not."""
    ctx = await _clinic(db, "recipient")
    patient = await _patient(db, "recipient", phone="+8801955006666")
    appointment = await _appointment(db, ctx, patient)

    with _use_test_session(db):
        await appointment_reminders.send_appointment_reminders()

    event = await db.scalar(
        select(OutboxEvent).where(OutboxEvent.event_type == EVENT_TYPE)
    )

    assert event.payload["user_id"] == patient.id
    assert event.payload["user_id"] != ctx["doctor_user"].id
    assert event.payload["appointment_id"] == appointment.id


@pytest.mark.asyncio
async def test_the_message_still_lands_a_day_ahead(db, channel_on, sent):
    """End to end at the new lead time: the job selects it, the worker dispatches
    it, and the patient's WhatsApp message carries the appointment's own local
    date and time — which is now genuinely tomorrow."""
    ctx = await _clinic(db, "e2e", timezone="Asia/Dhaka")
    patient = await _patient(db, "e2e", phone="+8801955007777")
    appointment = await _appointment(db, ctx, patient)

    with _use_test_session(db):
        await appointment_reminders.send_appointment_reminders()

    event = await db.scalar(
        select(OutboxEvent).where(OutboxEvent.event_type == EVENT_TYPE)
    )

    await handle_event(db, event)

    assert len(sent) == 1

    doctor, date, time = sent[0]["body_parameters"]

    local = appointment.scheduled_at.astimezone(
        __import__("zoneinfo").ZoneInfo("Asia/Dhaka")
    )

    assert doctor == "Dr. Rahman"
    assert date == local.strftime("%d %B")
    assert time == local.strftime("%I:%M %p")

    # The notice period, asserted as a duration rather than as a calendar-day
    # comparison. A "local date is tomorrow" assertion looks stronger and is
    # actually flaky: at 23-24 hours' notice the appointment falls on the next
    # local calendar day for all but one hour of the day, so such a test would
    # fail only when the suite happened to run between local midnight and 1am.
    #
    # That hour is a real (small) limitation of a fixed band and is recorded as
    # such, not papered over here.
    notice = appointment.scheduled_at - utc_now()

    assert timedelta(hours=23) <= notice <= timedelta(hours=24)

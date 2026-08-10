"""The reminder for an appointment confirmed inside the lead time.

THE GAP
A patient-initiated reschedule re-opens the appointment to PENDING. The scheduled
job selects only CONFIRMED appointments crossing the 23-24 hour band. So an
appointment rescheduled to tomorrow morning and confirmed this evening has passed
below the band while it was PENDING and can never re-enter it: the patient gets no
reminder at all. Resetting reminder_sent on reschedule — the previous milestone —
was necessary but not sufficient for exactly this case.

WHY NOT JUST WIDEN THE WINDOW
Making the job select 0-24 hours instead of 23-24 would cover this and reintroduce
the original defect: an appointment booked for this afternoon would immediately be
sent a message saying "tomorrow". The band exists to stop that.

So there are TWO ENTRY CONDITIONS into ONE reminder path:

    the job          an appointment CROSSING the 23-24 hour band
    confirmation     an appointment already INSIDE the lead time when confirmed

and everything downstream is shared: AppointmentReminderEvent,
publish_domain_event, the outbox, the dispatcher, the WhatsApp handler with its
preference, kill switch, template, patient-only validation, receipt and retry.
Nothing in appointment_service touches WhatsApp, and these tests assert that the
event is what carries the reminder — not a second sending path.

WHAT MAKES THE TWO PATHS EXCLUSIVE
reminder_sent, set in the same transaction as the event, exactly as the job does
it. The job filters on reminder_sent = False, so it cannot also claim a row this
path has committed; and it never sees a PENDING appointment, so it cannot have
claimed one first.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.constants import (
    APPOINTMENT_DURATION_MINUTES,
    REMINDER_LEAD_MINUTES,
)
from app.core.time import UTC, utc_now
from app.models.appointment import Appointment, AppointmentStatus
from app.models.notification import Notification
from app.models.notification_preference import NotificationPreference
from app.models.outbox_event import OutboxEvent
from app.models.patient import Gender, Patient
from app.models.user import User, UserRole
from app.services.appointment_service import (
    doctor_update_appointment_status,
    maybe_publish_immediate_reminder,
    patient_reschedule_appointment,
)
from app.services.event_handlers import notification_whatsapp_handler
from app.task import appointment_reminders
from app.try_except.exceptions import ForbiddenError, NotFoundError
from app.workers.outbox_worker import handle_event

from tests.task.test_appointment_reminder_event import _use_test_session

REMINDER = "APPOINTMENT_REMINDER"

TEMPLATE = "helpdoctor_appointment_reminder"


def _aligned(moment: datetime) -> datetime:
    moment = moment.replace(second=0, microsecond=0)

    return moment.replace(
        minute=moment.minute - (moment.minute % APPOINTMENT_DURATION_MINUTES)
    )


def _hours_away(hours: float) -> datetime:
    return _aligned(utc_now() + timedelta(hours=hours))


async def _appointment(
    db, doctor, patient_user, clinic, *, at,
    status=AppointmentStatus.PENDING, reminder_sent=False,
) -> Appointment:
    appointment = Appointment(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        clinic_id=getattr(clinic, "id", clinic),
        scheduled_at=at,
        status=status,
        reminder_sent=reminder_sent,
    )
    db.add(appointment)
    await db.flush()
    await db.refresh(appointment)

    return appointment


async def _reminders_for(db, appointment_id: int) -> list[OutboxEvent]:
    events = (
        await db.execute(
            select(OutboxEvent).where(OutboxEvent.event_type == REMINDER)
        )
    ).scalars().all()

    return [
        event for event in events
        if event.payload.get("appointment_id") == appointment_id
    ]


async def _confirm(db, doctor_user, appointment_id):
    return await doctor_update_appointment_status(
        db=db,
        doctor_user=doctor_user,
        appointment_id=appointment_id,
        new_status=AppointmentStatus.CONFIRMED,
    )


@pytest.fixture
def channel_on(monkeypatch):
    from app.config import get_settings

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


# ---------------------------------------------------------------------------
# The decision, in isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_pending_appointment_is_never_reminded(
    db, doctor, patient_user, default_clinic
):
    """Requirement 1. Nothing has been agreed to yet."""
    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_hours_away(5), status=AppointmentStatus.PENDING,
    )

    published = await maybe_publish_immediate_reminder(
        db=db, appointment=appointment
    )

    assert published is False
    assert await _reminders_for(db, appointment.id) == []
    assert appointment.reminder_sent is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("hours", "expected"),
    [
        (-3, False),      # already past
        (-0.5, False),    # started half an hour ago
        (0.5, True),      # half an hour away
        (1, True),        # requirement 3
        (12, True),
        (23, True),       # requirement 2
        (23.9, True),
        (25, False),      # requirement 8 / scheduler's job
        (48, False),
    ],
)
async def test_the_decision_boundaries(
    db, doctor, patient_user, default_clinic, hours, expected
):
    """The whole shape in one table.

    Inside the lead time and still in the future: remind now. Past: nothing to
    remind about. Beyond the lead time: the job will catch it as it crosses the
    band, and reminding now would be a day early.
    """
    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_hours_away(hours), status=AppointmentStatus.CONFIRMED,
    )

    published = await maybe_publish_immediate_reminder(
        db=db, appointment=appointment
    )

    assert published is expected
    assert len(await _reminders_for(db, appointment.id)) == (1 if expected else 0)
    assert appointment.reminder_sent is expected


@pytest.mark.asyncio
async def test_an_already_reminded_appointment_is_not_reminded_again(
    db, doctor, patient_user, default_clinic
):
    """Requirement 7. The shared guard, from this side."""
    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_hours_away(20), status=AppointmentStatus.CONFIRMED,
        reminder_sent=True,
    )

    assert await maybe_publish_immediate_reminder(
        db=db, appointment=appointment
    ) is False

    assert await _reminders_for(db, appointment.id) == []


@pytest.mark.asyncio
async def test_the_lead_time_is_the_scheduler_s_own_constant(db):
    """The two paths must agree on what "within a day" means.

    Imported from one place, so a service that thought the lead time was 12 hours
    could not hand appointments to a job that never selects them.
    """
    assert (
        appointment_reminders.REMINDER_LEAD_MINUTES == REMINDER_LEAD_MINUTES
    )


# ---------------------------------------------------------------------------
# Through the real reschedule → confirm flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reschedule_then_confirm_far_ahead_leaves_it_to_the_scheduler(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """Requirement 1 of the flow list, and requirement 5: more than a day away,
    so no immediate reminder — and reminder_sent stays False so the job can still
    pick it up when it crosses the band."""
    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_hours_away(50), status=AppointmentStatus.CONFIRMED,
    )

    await patient_reschedule_appointment(
        db=db, user=patient_user, appointment_id=appointment.id,
        new_datetime=_hours_away(60),
    )

    await db.refresh(appointment)
    assert appointment.status == AppointmentStatus.PENDING

    await _confirm(db, doctor_user, appointment.id)

    await db.refresh(appointment)

    assert appointment.status == AppointmentStatus.CONFIRMED
    assert await _reminders_for(db, appointment.id) == []
    assert appointment.reminder_sent is False, (
        "the appointment must stay eligible for the scheduled reminder"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("hours", [23, 12, 1])
async def test_reschedule_then_confirm_inside_the_lead_time_reminds_now(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user,
    hours,
):
    """Requirements 2 and 3 of the flow list.

    The full path: a confirmed appointment is rescheduled by the patient, drops to
    PENDING, and is confirmed when it is already inside the lead time — the case
    that previously produced no reminder ever.
    """
    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_hours_away(50), status=AppointmentStatus.CONFIRMED,
    )

    new_time = _hours_away(hours)

    await patient_reschedule_appointment(
        db=db, user=patient_user, appointment_id=appointment.id,
        new_datetime=new_time,
    )

    await _confirm(db, doctor_user, appointment.id)

    reminders = await _reminders_for(db, appointment.id)

    assert len(reminders) == 1

    await db.refresh(appointment)

    assert appointment.reminder_sent is True
    assert appointment.scheduled_at == new_time


@pytest.mark.asyncio
async def test_confirming_a_past_appointment_sends_no_reminder(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """Requirement 4 — and the past-time guard is LOAD-BEARING, not defensive.

    I expected confirmation itself to refuse this: appointment_status_service
    .confirm_appointment raises "Cannot confirm appointment after start time".
    That function is never called. The live route goes through
    doctor_update_appointment_status, which has no such check, so a past
    appointment confirms successfully.

    So the only thing standing between that and a reminder for an appointment that
    already happened is the guard in maybe_publish_immediate_reminder. Asserted
    here against the real flow rather than only as a unit.
    """
    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_hours_away(-4), status=AppointmentStatus.PENDING,
    )

    # Succeeds today. Left as an assertion of existing behaviour rather than
    # "fixed" here — tightening the status machine is not this milestone.
    await _confirm(db, doctor_user, appointment.id)

    await db.refresh(appointment)

    assert appointment.status == AppointmentStatus.CONFIRMED
    assert await _reminders_for(db, appointment.id) == []
    assert appointment.reminder_sent is False


@pytest.mark.asyncio
async def test_a_normal_confirmation_far_ahead_sends_nothing(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """Requirement 5. No reschedule involved: an ordinary booking confirmed well
    in advance must behave exactly as it did before this change."""
    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_hours_away(72), status=AppointmentStatus.PENDING,
    )

    await _confirm(db, doctor_user, appointment.id)

    assert await _reminders_for(db, appointment.id) == []


@pytest.mark.asyncio
async def test_confirmation_still_publishes_its_own_events(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """Requirement 13. The reminder is an addition — the two APPOINTMENT_CONFIRMED
    events, one per party, must be untouched."""
    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_hours_away(10), status=AppointmentStatus.PENDING,
    )

    await _confirm(db, doctor_user, appointment.id)

    confirmed = (
        await db.execute(
            select(OutboxEvent).where(
                OutboxEvent.event_type == "APPOINTMENT_CONFIRMED"
            )
        )
    ).scalars().all()

    mine = [
        event for event in confirmed
        if event.payload.get("appointment_id") == appointment.id
    ]

    assert len(mine) == 2

    recipients = {event.payload["user_id"] for event in mine}

    assert recipients == {patient_user.id, doctor.user_id}


# ---------------------------------------------------------------------------
# What the reminder says, and who gets it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_immediate_reminder_is_addressed_to_the_patient(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """Requirement 7 of the test list. Confirmation notifies both parties; a
    reminder goes only to whoever is attending."""
    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_hours_away(6), status=AppointmentStatus.PENDING,
    )

    await _confirm(db, doctor_user, appointment.id)

    reminder = (await _reminders_for(db, appointment.id))[0]

    assert reminder.payload["user_id"] == patient_user.id
    assert reminder.payload["user_id"] != doctor.user_id
    assert reminder.payload["appointment_id"] == appointment.id


@pytest.mark.asyncio
async def test_the_immediate_reminder_goes_through_the_reminder_event(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """No second sending path: the reminder must be an outbox event of the
    existing type, validating against the existing schema."""
    from app.schemas.event_registry import EVENT_SCHEMAS

    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_hours_away(6), status=AppointmentStatus.PENDING,
    )

    await _confirm(db, doctor_user, appointment.id)

    reminder = (await _reminders_for(db, appointment.id))[0]

    validated = EVENT_SCHEMAS[REMINDER].model_validate(reminder.payload)

    assert validated.appointment_id == appointment.id


@pytest.mark.asyncio
async def test_the_message_carries_the_new_appointment_time(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user,
    channel_on, sent,
):
    """Requirement 6, end to end and through the real WhatsApp handler: the
    patient is told the time they were actually rescheduled to."""
    db.add(NotificationPreference(
        user_id=patient_user.id, whatsapp_enabled=True
    ))
    await db.flush()

    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_hours_away(50), status=AppointmentStatus.CONFIRMED,
    )

    old_time = appointment.scheduled_at
    new_time = _hours_away(20)

    await patient_reschedule_appointment(
        db=db, user=patient_user, appointment_id=appointment.id,
        new_datetime=new_time,
    )

    await _confirm(db, doctor_user, appointment.id)

    reminder = (await _reminders_for(db, appointment.id))[0]

    await handle_event(db, reminder)

    assert len(sent) == 1
    assert sent[0]["template_name"] == TEMPLATE

    doctor_label, date, time = sent[0]["body_parameters"]

    from app.core.tz import to_zoneinfo
    from app.models.clinic import Clinic

    timezone = await db.scalar(
        select(Clinic.timezone).where(Clinic.id == appointment.clinic_id)
    )
    local = new_time.astimezone(to_zoneinfo(timezone))

    assert date == local.strftime("%d %B")
    assert time == local.strftime("%I:%M %p")

    # And emphatically not the slot the patient moved away from.
    old_local = old_time.astimezone(to_zoneinfo(timezone))

    if old_local.strftime("%I:%M %p") != local.strftime("%I:%M %p"):
        assert time != old_local.strftime("%I:%M %p")

    assert doctor_label.startswith("Dr.") or doctor_label == "your doctor"


# ---------------------------------------------------------------------------
# Only once, whichever path gets there
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_scheduler_will_not_remind_again_after_an_immediate_reminder(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """The race, resolved by the flag.

    Confirmed at 23 hours out, so the appointment is inside the lead time AND
    inside the band the job scans — both paths can see it. reminder_sent, written
    in the confirmation transaction, is what stops the second one.
    """
    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_hours_away(23.5), status=AppointmentStatus.PENDING,
    )

    await _confirm(db, doctor_user, appointment.id)

    assert len(await _reminders_for(db, appointment.id)) == 1

    for _ in range(3):
        with _use_test_session(db):
            await appointment_reminders.send_appointment_reminders()

    assert len(await _reminders_for(db, appointment.id)) == 1, (
        "the scheduler published a second reminder for the same appointment"
    )


@pytest.mark.asyncio
async def test_the_scheduler_cannot_have_claimed_a_pending_appointment_first(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """The other order of the race. The job filters on CONFIRMED, so a PENDING
    appointment sitting inside the band is invisible to it — which is why the
    immediate path cannot be the duplicate."""
    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_hours_away(23.5), status=AppointmentStatus.PENDING,
    )

    with _use_test_session(db):
        await appointment_reminders.send_appointment_reminders()

    assert await _reminders_for(db, appointment.id) == []

    await db.refresh(appointment)
    assert appointment.reminder_sent is False

    await _confirm(db, doctor_user, appointment.id)

    assert len(await _reminders_for(db, appointment.id)) == 1


@pytest.mark.asyncio
async def test_a_repeated_confirmation_does_not_remind_twice(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """Requirement 10, and reminder_sent is the only thing preventing it.

    I expected the status machine to refuse re-confirming an already-CONFIRMED
    appointment — appointment_status_service.confirm_appointment does exactly
    that, and is dead code. The live path allows it: a second confirmation
    succeeds and publishes another pair of APPOINTMENT_CONFIRMED events.

    So the duplicate-reminder guarantee rests entirely on reminder_sent, which is
    what this asserts.
    """
    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_hours_away(6), status=AppointmentStatus.PENDING,
    )

    await _confirm(db, doctor_user, appointment.id)

    assert len(await _reminders_for(db, appointment.id)) == 1

    # Permitted today, which is precisely why the flag has to hold.
    await _confirm(db, doctor_user, appointment.id)

    assert len(await _reminders_for(db, appointment.id)) == 1, (
        "a repeated confirmation published a second reminder"
    )


@pytest.mark.asyncio
async def test_the_immediate_reminder_is_delivered_once_and_recorded(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user,
    channel_on, sent,
):
    """Requirement 11: the existing receipt and idempotency semantics apply
    unchanged to a reminder that arrived by this route."""
    db.add(NotificationPreference(
        user_id=patient_user.id, whatsapp_enabled=True
    ))
    await db.flush()

    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_hours_away(6), status=AppointmentStatus.PENDING,
    )

    await _confirm(db, doctor_user, appointment.id)

    reminder = (await _reminders_for(db, appointment.id))[0]

    await handle_event(db, reminder)
    await handle_event(db, reminder)
    await handle_event(db, reminder)

    assert len(sent) == 1

    stored = await db.scalar(
        select(Notification).where(
            Notification.event_id == reminder.id,
            Notification.user_id == patient_user.id,
        )
    )

    assert stored.whatsapp_delivered_at is not None


@pytest.mark.asyncio
async def test_a_failed_immediate_reminder_stays_retryable(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user,
    channel_on, monkeypatch,
):
    """Requirement 9. Failure semantics are the handler's, and are unchanged by
    the new entry condition."""
    db.add(NotificationPreference(
        user_id=patient_user.id, whatsapp_enabled=True
    ))
    await db.flush()

    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_hours_away(6), status=AppointmentStatus.PENDING,
    )

    await _confirm(db, doctor_user, appointment.id)

    reminder = (await _reminders_for(db, appointment.id))[0]

    async def _fail(**kwargs):
        raise RuntimeError("meta is down")

    monkeypatch.setattr(
        notification_whatsapp_handler.WhatsAppService, "send_template", _fail
    )

    with pytest.raises(RuntimeError):
        await handle_event(db, reminder)

    stored = await db.scalar(
        select(Notification).where(
            Notification.event_id == reminder.id,
            Notification.user_id == patient_user.id,
        )
    )

    assert stored.whatsapp_delivered_at is None
    assert stored.whatsapp_failed_at is not None

    ok = []

    async def _ok(**kwargs):
        ok.append(kwargs)
        return {}

    monkeypatch.setattr(
        notification_whatsapp_handler.WhatsAppService, "send_template", _ok
    )

    await handle_event(db, reminder)

    assert len(ok) == 1


# ---------------------------------------------------------------------------
# Atomicity and isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_publish_takes_the_confirmation_with_it(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user,
    monkeypatch,
):
    """Requirement: the confirmation transaction stays atomic.

    No independent commit for the reminder — so if publishing the reminder event
    fails, the confirmation itself must not survive.
    """
    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_hours_away(6), status=AppointmentStatus.PENDING,
    )

    appointment_id = appointment.id

    await db.commit()

    calls = {"n": 0}

    real = maybe_publish_immediate_reminder.__globals__["publish_domain_event"]

    async def _fail_on_reminder(*, db, event):
        if event.event_type == REMINDER:
            raise RuntimeError("outbox is unavailable")

        calls["n"] += 1

        return await real(db=db, event=event)

    monkeypatch.setattr(
        "app.services.appointment_service.publish_domain_event",
        _fail_on_reminder,
    )

    with pytest.raises(RuntimeError):
        await _confirm(db, doctor_user, appointment_id)

    await db.rollback()

    row = await db.scalar(
        select(Appointment).where(Appointment.id == appointment_id)
    )

    assert row.status == AppointmentStatus.PENDING, (
        "the confirmation survived a failed reminder publish"
    )
    assert row.reminder_sent is False


@pytest.mark.asyncio
async def test_another_clinics_appointment_cannot_be_confirmed(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """Requirement 12. Confirmation scopes its lookup to the caller's clinic, so
    no reminder can be triggered for another clinic's appointment."""
    from app.models.clinic import Clinic, ClinicStatus
    from app.models.doctor import Doctor, DoctorStatus

    other_clinic = Clinic(
        name="Other Confirm Clinic", status=ClinicStatus.ACTIVE, timezone="UTC"
    )
    db.add(other_clinic)
    await db.flush()

    other_doctor_user = User(
        email="other-confirm-doc@example.com", full_name="Other Doc",
        hashed_password="x", role=UserRole.DOCTOR, is_active=True,
        clinic_id=other_clinic.id,
    )
    db.add(other_doctor_user)
    await db.flush()

    other_doctor = Doctor(
        user_id=other_doctor_user.id, clinic_id=other_clinic.id,
        specialization="Medicine", experience_years=1, bio="b",
        status=DoctorStatus.APPROVED,
    )
    db.add(other_doctor)
    await db.flush()

    other_patient = User(
        email="other-confirm-patient@example.com", full_name="Other",
        hashed_password="x", role=UserRole.PATIENT, is_active=True,
    )
    db.add(other_patient)
    await db.flush()

    db.add(Patient(
        user_id=other_patient.id, phone="+8801977000111", address="a",
        date_of_birth=utc_now().date(), gender=Gender.MALE,
    ))
    await db.flush()

    foreign = await _appointment(
        db, other_doctor, other_patient, other_clinic,
        at=_hours_away(6), status=AppointmentStatus.PENDING,
    )

    foreign_id = foreign.id

    await db.commit()

    with pytest.raises((NotFoundError, ForbiddenError)):
        await _confirm(db, doctor_user, foreign_id)

    await db.rollback()

    assert await _reminders_for(db, foreign_id) == []

    surviving = await db.scalar(
        select(Appointment.reminder_sent).where(Appointment.id == foreign_id)
    )

    assert surviving is False


@pytest.mark.asyncio
async def test_confirming_one_appointment_does_not_remind_another(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """A reminder published with the wrong appointment_id, or a flag written on
    the wrong row, would show up here."""
    untouched = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_hours_away(8), status=AppointmentStatus.PENDING,
    )

    confirming = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_hours_away(6), status=AppointmentStatus.PENDING,
    )

    await _confirm(db, doctor_user, confirming.id)

    assert len(await _reminders_for(db, confirming.id)) == 1
    assert await _reminders_for(db, untouched.id) == []

    await db.refresh(untouched)

    assert untouched.reminder_sent is False
    assert untouched.status == AppointmentStatus.PENDING


# ---------------------------------------------------------------------------
# One sending path, structurally
# ---------------------------------------------------------------------------


def test_appointment_service_never_reaches_for_the_whatsapp_client():
    """Parsed, not grepped.

    The docstring of maybe_publish_immediate_reminder names WhatsApp on purpose —
    to explain what it deliberately does NOT touch — so a text search would trip
    over its own explanation. This looks at imports and calls.

    The rule it defends: appointment confirmation publishes a domain event and
    knows nothing about channels. A direct send here would bypass the preference,
    the kill switch, the template configuration, the patient-only validation, the
    receipt and the retry — all of which live in the handler.
    """
    import ast
    from pathlib import Path

    import app.services.appointment_service as service

    tree = ast.parse(Path(service.__file__).read_text())

    imported = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)

    offenders = {
        name for name in imported
        if "whatsapp" in name.lower() or "email" in name.lower()
        or name in {"send_push_notification_task", "notify_user"}
    }

    assert not offenders, (
        f"appointment_service imports a delivery channel: {sorted(offenders)}"
    )

    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "send_template" not in called
    assert "send_document" not in called


def test_the_reminder_is_published_as_the_reminder_event():
    """The only event type this path may publish for a reminder.

    Pinned structurally as well as behaviourally: publishing some other event —
    or building an OutboxEvent by hand — would be a second reminder architecture,
    which is the thing the milestone forbids.
    """
    import ast
    import inspect

    from app.services.appointment_service import (
        maybe_publish_immediate_reminder,
    )

    source = inspect.getsource(maybe_publish_immediate_reminder)

    tree = ast.parse(source.lstrip())

    constructed = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "AppointmentReminderEvent" in constructed, (
        "the immediate reminder does not publish AppointmentReminderEvent"
    )
    assert "OutboxEvent" not in constructed, (
        "the immediate reminder builds an outbox row by hand"
    )

    awaited = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "publish_domain_event" in awaited

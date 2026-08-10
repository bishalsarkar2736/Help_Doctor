"""The last way an appointment could sit inside the lead time and never be reminded.

THE GAP
A doctor-initiated reschedule keeps the appointment CONFIRMED and goes through
apply_reschedule_side_effects, not the confirmation path. So moving a confirmed
appointment from three days out to twenty hours out re-armed reminder_sent (the
reschedule milestone) and then reminded nobody: the scheduled job only selects
appointments CROSSING the 23-24 hour band, and this one is already below it.

That completes the set. An appointment can enter the lead time three ways —
crossing the band on its own, being confirmed once already inside it, or being
moved into it — and all three now reach the same reminder.

ONE DECISION, THREE ENTRY POINTS
No new helper. apply_reschedule_side_effects calls the SAME
maybe_publish_immediate_reminder that apply_confirmation_side_effects calls, and
the helper re-checks status, the flag, the past and the lead time itself. That is
what makes the shared call safe on the patient reschedule path, which leaves the
appointment PENDING: the helper declines, and nothing is sent until a doctor
confirms.

A second helper would have been the obvious way to write this and the wrong one:
two copies of "is this inside the lead time" are free to disagree, and the one
that drifts low silently stops reminding.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.constants import APPOINTMENT_DURATION_MINUTES
from app.core.time import utc_now
from app.models.appointment import Appointment, AppointmentStatus
from app.models.notification import Notification
from app.models.notification_preference import NotificationPreference
from app.models.outbox_event import OutboxEvent
from app.models.patient import Gender, Patient
from app.models.user import User, UserRole
from app.services.appointment_service import doctor_reschedule_appointment
from app.services.event_handlers import notification_whatsapp_handler
from app.task import appointment_reminders
from app.try_except.exceptions import BadRequestError, NotFoundError
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


async def _confirmed(
    db, doctor, patient_user, clinic, *, at, reminder_sent=False
) -> Appointment:
    appointment = Appointment(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        clinic_id=getattr(clinic, "id", clinic),
        scheduled_at=at,
        status=AppointmentStatus.CONFIRMED,
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


async def _reschedule(db, doctor_user, appointment_id, new_datetime):
    return await doctor_reschedule_appointment(
        db=db,
        doctor_user=doctor_user,
        appointment_id=appointment_id,
        new_datetime=new_datetime,
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
# The boundary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rescheduling_further_ahead_leaves_it_to_the_scheduler(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """Requirement 1. Still more than a day out, so no immediate reminder — and
    reminder_sent must be re-armed so the job can do its ordinary work later."""
    appointment = await _confirmed(
        db, doctor, patient_user, default_clinic,
        at=_hours_away(72), reminder_sent=True,
    )

    await _reschedule(db, doctor_user, appointment.id, _hours_away(96))

    await db.refresh(appointment)

    assert appointment.status == AppointmentStatus.CONFIRMED
    assert appointment.reminder_sent is False, (
        "the appointment is no longer eligible for the scheduled reminder"
    )
    assert await _reminders_for(db, appointment.id) == []

    # And the job leaves it alone for now, because it is above the band.
    with _use_test_session(db):
        await appointment_reminders.send_appointment_reminders()

    assert await _reminders_for(db, appointment.id) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("hours", "expected"),
    [
        (96, False),     # requirement 1
        (48, False),
        (26, False),
        (24, True),      # requirement 2 — at the lead time itself
        (23, True),      # requirement 3
        (12, True),      # requirement 4
        (1, True),       # requirement 5
        (0.5, True),
    ],
)
async def test_the_reschedule_boundary(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user,
    hours, expected,
):
    """Requirements 1-5 in one table, through the real reschedule call.

    24 hours counts as inside: the appointment is fixed when the test builds it and
    the helper's clock has moved on by the time it decides, so an appointment
    placed exactly at the lead time is marginally within it. Anything a margin
    above — 26 hours here — belongs to the job.
    """
    appointment = await _confirmed(
        db, doctor, patient_user, default_clinic, at=_hours_away(72)
    )

    await _reschedule(db, doctor_user, appointment.id, _hours_away(hours))

    reminders = await _reminders_for(db, appointment.id)

    assert len(reminders) == (1 if expected else 0)

    await db.refresh(appointment)

    assert appointment.reminder_sent is expected
    assert appointment.status == AppointmentStatus.CONFIRMED


@pytest.mark.asyncio
async def test_rescheduling_into_the_past_is_refused_outright(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """Requirement 6. The reschedule itself rejects a past time, so no reminder
    can follow — asserted rather than assumed, since the helper's own past guard
    would otherwise be the only thing standing there."""
    appointment = await _confirmed(
        db, doctor, patient_user, default_clinic, at=_hours_away(72)
    )

    appointment_id = appointment.id

    with pytest.raises(BadRequestError):
        await _reschedule(db, doctor_user, appointment_id, _hours_away(-3))

    await db.rollback()

    assert await _reminders_for(db, appointment_id) == []


# ---------------------------------------------------------------------------
# A reschedule that moves nothing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_no_op_reschedule_does_not_rearm_or_remind(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """Requirement 7. Resubmitting the same slot must not re-arm the flag, and
    must not produce a second reminder for an appointment already reminded."""
    at = _hours_away(20)

    appointment = await _confirmed(
        db, doctor, patient_user, default_clinic, at=at, reminder_sent=True,
    )

    await _reschedule(db, doctor_user, appointment.id, at)

    await db.refresh(appointment)

    assert appointment.reminder_sent is True, (
        "a no-op reschedule re-armed the reminder"
    )
    assert await _reminders_for(db, appointment.id) == []
    assert appointment.scheduled_at == at


@pytest.mark.asyncio
async def test_a_resubmitted_reschedule_cannot_duplicate_the_reminder(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """Requirement 12. The first move into the lead time reminds; submitting the
    same new time again is a no-op and must not remind twice."""
    appointment = await _confirmed(
        db, doctor, patient_user, default_clinic, at=_hours_away(72)
    )

    new_time = _hours_away(20)

    await _reschedule(db, doctor_user, appointment.id, new_time)

    assert len(await _reminders_for(db, appointment.id)) == 1

    await _reschedule(db, doctor_user, appointment.id, new_time)

    assert len(await _reminders_for(db, appointment.id)) == 1, (
        "a resubmitted reschedule published a second reminder"
    )


@pytest.mark.asyncio
async def test_moving_again_to_a_different_time_reminds_again(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """The counterpart, and deliberately NOT treated as a duplicate: a second
    move is a second time the patient needs to know about."""
    appointment = await _confirmed(
        db, doctor, patient_user, default_clinic, at=_hours_away(72)
    )

    await _reschedule(db, doctor_user, appointment.id, _hours_away(20))
    await _reschedule(db, doctor_user, appointment.id, _hours_away(18))

    assert len(await _reminders_for(db, appointment.id)) == 2


# ---------------------------------------------------------------------------
# What the reminder says, and who receives it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_reminder_is_addressed_to_the_patient(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """Requirement 9. The doctor performed the reschedule and is notified of it
    separately; the reminder is for whoever is attending."""
    appointment = await _confirmed(
        db, doctor, patient_user, default_clinic, at=_hours_away(72)
    )

    await _reschedule(db, doctor_user, appointment.id, _hours_away(20))

    reminder = (await _reminders_for(db, appointment.id))[0]

    assert reminder.payload["user_id"] == patient_user.id
    assert reminder.payload["user_id"] != doctor.user_id
    assert reminder.payload["user_id"] != doctor_user.id


@pytest.mark.asyncio
async def test_the_reminder_carries_the_new_time_not_the_old_one(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user,
    channel_on, sent,
):
    """Requirement 8, through the real WhatsApp handler and in the clinic's own
    timezone."""
    db.add(NotificationPreference(
        user_id=patient_user.id, whatsapp_enabled=True
    ))
    await db.flush()

    old_time = _hours_away(72)

    appointment = await _confirmed(
        db, doctor, patient_user, default_clinic, at=old_time
    )

    new_time = _hours_away(20)

    await _reschedule(db, doctor_user, appointment.id, new_time)

    reminder = (await _reminders_for(db, appointment.id))[0]

    await handle_event(db, reminder)

    assert len(sent) == 1

    from app.core.tz import to_zoneinfo
    from app.models.clinic import Clinic

    timezone = await db.scalar(
        select(Clinic.timezone).where(Clinic.id == appointment.clinic_id)
    )

    local_new = new_time.astimezone(to_zoneinfo(timezone))
    local_old = old_time.astimezone(to_zoneinfo(timezone))

    _, date, time = sent[0]["body_parameters"]

    assert date == local_new.strftime("%d %B")
    assert time == local_new.strftime("%I:%M %p")

    assert date != local_old.strftime("%d %B"), (
        "the reminder announced the slot the patient was moved away from"
    )


@pytest.mark.asyncio
async def test_no_internal_id_reaches_the_message(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user,
    channel_on, sent,
):
    db.add(NotificationPreference(
        user_id=patient_user.id, whatsapp_enabled=True
    ))
    await db.flush()

    appointment = await _confirmed(
        db, doctor, patient_user, default_clinic, at=_hours_away(72)
    )

    await _reschedule(db, doctor_user, appointment.id, _hours_away(20))

    reminder = (await _reminders_for(db, appointment.id))[0]

    await handle_event(db, reminder)

    forbidden = {
        str(appointment.id), str(patient_user.id),
        str(doctor.id), str(doctor_user.id), str(default_clinic.id),
    }

    for value in sent[0]["body_parameters"]:
        assert value not in forbidden


# ---------------------------------------------------------------------------
# Delivery, idempotency, retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exactly_one_reminder_is_delivered(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user,
    channel_on, sent,
):
    """Requirement 11, plus 13 of the previous milestone's list: the existing
    receipt and idempotency semantics apply unchanged to a reminder that arrived
    by this route."""
    db.add(NotificationPreference(
        user_id=patient_user.id, whatsapp_enabled=True
    ))
    await db.flush()

    appointment = await _confirmed(
        db, doctor, patient_user, default_clinic, at=_hours_away(72)
    )

    await _reschedule(db, doctor_user, appointment.id, _hours_away(20))

    reminders = await _reminders_for(db, appointment.id)

    assert len(reminders) == 1

    for _ in range(3):
        await handle_event(db, reminders[0])

    assert len(sent) == 1

    stored = await db.scalar(
        select(Notification).where(
            Notification.event_id == reminders[0].id,
            Notification.user_id == patient_user.id,
        )
    )

    assert stored.whatsapp_delivered_at is not None


@pytest.mark.asyncio
async def test_a_failed_delivery_stays_retryable(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user,
    channel_on, monkeypatch,
):
    """Requirement 14 of the preserve list."""
    db.add(NotificationPreference(
        user_id=patient_user.id, whatsapp_enabled=True
    ))
    await db.flush()

    appointment = await _confirmed(
        db, doctor, patient_user, default_clinic, at=_hours_away(72)
    )

    await _reschedule(db, doctor_user, appointment.id, _hours_away(20))

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


@pytest.mark.asyncio
async def test_the_scheduler_will_not_remind_again(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """Both entry conditions can see an appointment moved to 23.5 hours out.
    reminder_sent, written in the reschedule transaction, is what keeps it to one
    message."""
    appointment = await _confirmed(
        db, doctor, patient_user, default_clinic, at=_hours_away(72)
    )

    await _reschedule(db, doctor_user, appointment.id, _hours_away(23.5))

    assert len(await _reminders_for(db, appointment.id)) == 1

    for _ in range(3):
        with _use_test_session(db):
            await appointment_reminders.send_appointment_reminders()

    assert len(await _reminders_for(db, appointment.id)) == 1


# ---------------------------------------------------------------------------
# Atomicity and isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_reminder_publish_rolls_back_the_reschedule(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user,
    monkeypatch,
):
    """Requirement 10, and requirement 15 of the preserve list.

    No separate commit for the reminder: if publishing it fails, the appointment
    must still be at its original time afterwards.
    """
    old_time = _hours_away(72)

    appointment = await _confirmed(
        db, doctor, patient_user, default_clinic, at=old_time
    )

    appointment_id = appointment.id

    await db.commit()

    from app.services import appointment_service

    real = appointment_service.publish_domain_event

    async def _fail_on_reminder(*, db, event):
        if event.event_type == REMINDER:
            raise RuntimeError("outbox is unavailable")

        return await real(db=db, event=event)

    monkeypatch.setattr(
        appointment_service, "publish_domain_event", _fail_on_reminder
    )

    with pytest.raises(RuntimeError):
        await _reschedule(db, doctor_user, appointment_id, _hours_away(20))

    await db.rollback()

    row = await db.scalar(
        select(Appointment).where(Appointment.id == appointment_id)
    )

    assert row.scheduled_at == old_time, (
        "the reschedule survived a failed reminder publish"
    )
    assert row.reminder_sent is False
    assert await _reminders_for(db, appointment_id) == []


@pytest.mark.asyncio
async def test_another_clinics_appointment_cannot_be_rescheduled(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """Requirement 13. Scoped by the caller's clinic, so no reminder can be
    triggered for another clinic's appointment."""
    from app.models.clinic import Clinic, ClinicStatus
    from app.models.doctor import Doctor, DoctorStatus

    other_clinic = Clinic(
        name="Other Resched Clinic", status=ClinicStatus.ACTIVE, timezone="UTC"
    )
    db.add(other_clinic)
    await db.flush()

    other_doctor_user = User(
        email="other-resched-doc@example.com", full_name="Other Doc",
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
        email="other-resched-patient@example.com", full_name="Other",
        hashed_password="x", role=UserRole.PATIENT, is_active=True,
    )
    db.add(other_patient)
    await db.flush()

    db.add(Patient(
        user_id=other_patient.id, phone="+8801988000111", address="a",
        date_of_birth=utc_now().date(), gender=Gender.MALE,
    ))
    await db.flush()

    foreign = await _confirmed(
        db, other_doctor, other_patient, other_clinic, at=_hours_away(72)
    )

    foreign_id = foreign.id

    await db.commit()

    with pytest.raises(NotFoundError):
        await _reschedule(db, doctor_user, foreign_id, _hours_away(20))

    await db.rollback()

    assert await _reminders_for(db, foreign_id) == []

    surviving = await db.scalar(
        select(Appointment.reminder_sent).where(Appointment.id == foreign_id)
    )

    assert surviving is False


@pytest.mark.asyncio
async def test_rescheduling_one_appointment_does_not_remind_another(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """A reminder published with the wrong appointment_id, or a flag written on
    the wrong row, would surface here."""
    untouched = await _confirmed(
        db, doctor, patient_user, default_clinic,
        at=_hours_away(19), reminder_sent=True,
    )

    moving = await _confirmed(
        db, doctor, patient_user, default_clinic, at=_hours_away(72)
    )

    await _reschedule(db, doctor_user, moving.id, _hours_away(20))

    assert len(await _reminders_for(db, moving.id)) == 1
    assert await _reminders_for(db, untouched.id) == []

    await db.refresh(untouched)

    assert untouched.reminder_sent is True
    assert untouched.scheduled_at == _hours_away(19)


# ---------------------------------------------------------------------------
# One implementation of the decision
# ---------------------------------------------------------------------------


def test_there_is_exactly_one_immediate_reminder_decision():
    """Both side-effect groups must call the same helper.

    Asserted on the code, because the failure mode is a second implementation
    that looks right today and drifts later — two copies of "is this inside the
    lead time", the lower one silently reminding nobody.
    """
    import ast
    from pathlib import Path

    import app.services.appointment_service as service

    tree = ast.parse(Path(service.__file__).read_text())

    definitions = [
        node.name for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and "immediate_reminder" in node.name
    ]

    assert definitions == ["maybe_publish_immediate_reminder"], (
        f"more than one immediate-reminder implementation: {definitions}"
    )

    # And no lookalike sibling under another name.
    forbidden = {
        node.name for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {
            "maybe_publish_reschedule_reminder",
            "send_whatsapp_reminder",
            "publish_reschedule_reminder",
        }
    }

    assert not forbidden, f"a second reminder path was added: {forbidden}"


def test_both_side_effect_groups_call_the_shared_helper():
    """The reschedule group and the confirmation group, each reaching the one
    decision — so neither path can quietly lose its reminder."""
    import ast
    import inspect

    from app.services.appointment_service import (
        apply_confirmation_side_effects,
        apply_reschedule_side_effects,
    )

    for function in (apply_reschedule_side_effects, apply_confirmation_side_effects):
        tree = ast.parse(inspect.getsource(function).lstrip())

        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }

        assert "maybe_publish_immediate_reminder" in called, (
            f"{function.__name__} does not reach the shared reminder decision"
        )

        assert "AppointmentReminderEvent" not in called, (
            f"{function.__name__} builds its own reminder event"
        )


@pytest.mark.asyncio
async def test_a_successful_reminder_is_not_committed_on_its_own(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user,
    monkeypatch,
):
    """The reminder must not commit anything by itself.

    Distinct from the rollback test above, and it took a surviving mutant to
    notice: that one makes the PUBLISH fail, so a stray commit inside the helper
    is never reached and the mutant lives. Here the publish SUCCEEDS and the
    transaction fails afterwards — log_activity, which runs after the side
    effects — so anything the helper committed early would survive a reschedule
    that did not happen.
    """
    from app.services import appointment_service

    old_time = _hours_away(72)

    appointment = await _confirmed(
        db, doctor, patient_user, default_clinic, at=old_time
    )

    appointment_id = appointment.id

    await db.commit()

    async def _boom(**kwargs):
        raise RuntimeError("activity log unavailable")

    monkeypatch.setattr(appointment_service, "log_activity", _boom)

    with pytest.raises(RuntimeError):
        await _reschedule(db, doctor_user, appointment_id, _hours_away(20))

    await db.rollback()

    row = await db.scalar(
        select(Appointment).where(Appointment.id == appointment_id)
    )

    assert row.scheduled_at == old_time, (
        "the reschedule was committed before the transaction completed"
    )
    assert row.reminder_sent is False, (
        "reminder_sent was committed independently of the reschedule"
    )
    assert await _reminders_for(db, appointment_id) == [], (
        "the reminder event was committed on its own"
    )

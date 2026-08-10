"""A rescheduled appointment must get a reminder for its NEW time.

THE BUG
reminder_sent is one-shot. The reminder job selects appointments 23-24 hours out
with reminder_sent = False, publishes a reminder and sets the flag; it never looks
at that row again. That is right until the appointment moves.

Move it, and the patient has been reminded of a time that no longer exists while
the flag still says they were told — so the job skips the row forever and the new
time is never announced. The patient's only reminder is for the wrong slot.

It became consequential only recently. While the job used a 60-minute window
almost nothing was ever reminded, so almost nothing carried a stale flag; now
that reminders actually go out a day ahead, most rescheduled appointments would
carry one.

THE FIX, AND WHAT THESE TESTS PIN
move_appointment_to sets the time and clears the flag together, and clears it
ONLY when the instant actually changes — a resubmitted form must not earn the
patient a second identical reminder.

Neither reschedule function commits: the route's transaction owns the whole
operation. So the reset is atomic with the status transition, the outbox event and
the activity log, and a reschedule that fails on the double-booking constraint
leaves the old reminder state exactly as it was. That is asserted, not assumed.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.constants import APPOINTMENT_DURATION_MINUTES
from app.core.time import UTC, utc_now
from app.models.appointment import Appointment, AppointmentStatus
from app.models.notification_preference import NotificationPreference
from app.models.outbox_event import OutboxEvent
from app.models.patient import Gender, Patient
from app.models.user import User, UserRole
from app.services.appointment_service import (
    doctor_reschedule_appointment,
    move_appointment_to,
    patient_reschedule_appointment,
)
from app.task import appointment_reminders
from app.task.appointment_reminders import REMINDER_LEAD_MINUTES
from app.try_except.exceptions import BadRequestError, NotFoundError

# Reuse the reminder suite's session override rather than a second copy.
from tests.task.test_appointment_reminder_event import _use_test_session


def _aligned(moment: datetime) -> datetime:
    """Snap to a slot boundary, the way the existing reschedule tests do."""
    moment = moment.replace(second=0, microsecond=0)

    return moment.replace(
        minute=moment.minute - (moment.minute % APPOINTMENT_DURATION_MINUTES)
    )


def _in_band(minutes_before_lead: int = 30) -> datetime:
    """A time inside the reminder band, so the job selects it."""
    return _aligned(
        utc_now() + timedelta(minutes=REMINDER_LEAD_MINUTES - minutes_before_lead)
    )


def _outside_band(days_ahead: int = 5) -> datetime:
    return _aligned(
        (utc_now() + timedelta(days=days_ahead)).replace(hour=10)
    )


async def _appointment(
    db, doctor, patient_user, clinic, *, at,
    status=AppointmentStatus.CONFIRMED, reminder_sent=False,
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


async def _opt_in(db, user_id: int) -> None:
    db.add(NotificationPreference(user_id=user_id, whatsapp_enabled=True))
    await db.flush()


async def _run_job(db) -> None:
    with _use_test_session(db):
        await appointment_reminders.send_appointment_reminders()


async def _reminders_for(db, appointment_id: int) -> list[OutboxEvent]:
    events = (
        await db.execute(
            select(OutboxEvent).where(
                OutboxEvent.event_type == "APPOINTMENT_REMINDER"
            )
        )
    ).scalars().all()

    return [
        event for event in events
        if event.payload.get("appointment_id") == appointment_id
    ]


# ---------------------------------------------------------------------------
# The flag, on its own
# ---------------------------------------------------------------------------


def test_moving_an_appointment_rearms_the_reminder():
    """The unit, with no database in the way."""
    appointment = Appointment(
        scheduled_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        reminder_sent=True,
    )

    changed = move_appointment_to(
        appointment, datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
    )

    assert changed is True
    assert appointment.reminder_sent is False
    assert appointment.scheduled_at == datetime(2026, 9, 2, 10, 0, tzinfo=UTC)


def test_moving_an_appointment_to_the_same_instant_changes_nothing():
    """A resubmitted form must not earn the patient a second reminder."""
    at = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)

    appointment = Appointment(scheduled_at=at, reminder_sent=True)

    changed = move_appointment_to(appointment, at)

    assert changed is False
    assert appointment.reminder_sent is True


def test_the_same_instant_in_another_offset_is_not_a_change():
    """Compared as instants, not as wall clocks, so a client sending +06:00
    instead of Z does not re-arm anything."""
    from datetime import timezone

    appointment = Appointment(
        scheduled_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        reminder_sent=True,
    )

    same_moment = datetime(
        2026, 9, 1, 16, 0, tzinfo=timezone(timedelta(hours=6))
    )

    assert move_appointment_to(appointment, same_moment) is False
    assert appointment.reminder_sent is True


def test_an_unreminded_appointment_is_left_alone():
    """Nothing to re-arm, and the flag must not be set as a side effect."""
    appointment = Appointment(
        scheduled_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        reminder_sent=False,
    )

    move_appointment_to(appointment, datetime(2026, 9, 3, 10, 0, tzinfo=UTC))

    assert appointment.reminder_sent is False


# ---------------------------------------------------------------------------
# Through the real reschedule flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unreminded_appointment_receives_its_normal_reminder(
    db, doctor, doctor_availability, patient_user, default_clinic
):
    """Requirement 1, and the baseline the rest of this file depends on."""
    appointment = await _appointment(
        db, doctor, patient_user, default_clinic, at=_in_band()
    )

    await _run_job(db)

    await db.refresh(appointment)

    assert appointment.reminder_sent is True
    assert len(await _reminders_for(db, appointment.id)) == 1


@pytest.mark.asyncio
async def test_a_reminded_appointment_is_not_reminded_again(
    db, doctor, doctor_availability, patient_user, default_clinic
):
    """Requirement 2. The one-shot flag is correct behaviour when nothing moves —
    this is what the fix must not break."""
    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_in_band(), reminder_sent=True,
    )

    await _run_job(db)

    assert await _reminders_for(db, appointment.id) == []


@pytest.mark.asyncio
async def test_rescheduling_resets_the_reminder_state(
    db, doctor, doctor_availability, patient_user, default_clinic
):
    """Requirement 3, through the patient's own reschedule path."""
    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_outside_band(2), reminder_sent=True,
    )

    await patient_reschedule_appointment(
        db=db,
        user=patient_user,
        appointment_id=appointment.id,
        new_datetime=_outside_band(4),
    )

    await db.refresh(appointment)

    assert appointment.reminder_sent is False


@pytest.mark.asyncio
async def test_the_doctors_reschedule_path_also_resets_it(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """Both paths move appointments, so both must re-arm. Written separately
    because two call sites are two chances to fix only one."""
    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_outside_band(2), reminder_sent=True,
    )

    await doctor_reschedule_appointment(
        db=db,
        doctor_user=doctor_user,
        appointment_id=appointment.id,
        new_datetime=_outside_band(4),
    )

    await db.refresh(appointment)

    assert appointment.reminder_sent is False


@pytest.mark.asyncio
async def test_the_rescheduled_appointment_then_enters_the_band(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """Requirements 4 and 5: the reset is only useful if a reminder actually
    follows it, so this runs the job afterwards and reads the payload."""
    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_outside_band(5), reminder_sent=True,
    )

    # Out of the band, so the job would ignore it either way.
    await _run_job(db)
    assert await _reminders_for(db, appointment.id) == []

    new_time = _in_band()

    # The DOCTOR's path deliberately. A patient-initiated reschedule re-opens the
    # appointment to PENDING and the reminder job only selects CONFIRMED, so a
    # patient reschedule earns no reminder until the doctor confirms it — correct
    # behaviour, and it would make this test pass for the wrong reason.
    await doctor_reschedule_appointment(
        db=db,
        doctor_user=doctor_user,
        appointment_id=appointment.id,
        new_datetime=new_time,
    )

    await _run_job(db)

    reminders = await _reminders_for(db, appointment.id)

    assert len(reminders) == 1
    assert reminders[0].payload["user_id"] == patient_user.id

    await db.refresh(appointment)

    assert appointment.scheduled_at == new_time
    assert appointment.reminder_sent is True


@pytest.mark.asyncio
async def test_the_reminder_carries_the_new_time_and_not_the_old_one(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """Requirement 6, asserted on what the patient would be told.

    The reminder message renders appointment.scheduled_at, so the check is that
    the row the job reminded about holds the new instant — the old one must be
    gone, not merely accompanied by the new one.
    """
    old_time = _outside_band(5)

    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=old_time, reminder_sent=True,
    )

    new_time = _in_band()

    await doctor_reschedule_appointment(
        db=db,
        doctor_user=doctor_user,
        appointment_id=appointment.id,
        new_datetime=new_time,
    )

    await _run_job(db)

    assert len(await _reminders_for(db, appointment.id)) == 1

    reminded = await db.scalar(
        select(Appointment.scheduled_at).where(
            Appointment.id == appointment.id
        )
    )

    assert reminded == new_time
    assert reminded != old_time


@pytest.mark.asyncio
async def test_rescheduling_to_the_same_time_does_not_reset_the_flag(
    db, doctor, doctor_availability, patient_user, default_clinic
):
    """Requirement 7. The guard against a second identical reminder."""
    at = _outside_band(3)

    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=at, reminder_sent=True,
    )

    await patient_reschedule_appointment(
        db=db,
        user=patient_user,
        appointment_id=appointment.id,
        new_datetime=at,
    )

    await db.refresh(appointment)

    assert appointment.reminder_sent is True, (
        "a no-op reschedule re-armed the reminder"
    )


@pytest.mark.asyncio
async def test_a_failed_reschedule_leaves_the_reminder_state_alone(
    db, doctor, doctor_availability, patient_user, default_clinic
):
    """Requirement 8, and the reason the reset lives inside the caller's
    transaction rather than being committed on its own.

    The failure used here is the real one: the exclusion constraint refusing to
    put a doctor in two places at once. That rejection happens on the same flush
    that writes the reset, so if the reset were committed separately it would
    survive a reschedule that did not happen.
    """
    taken = _outside_band(6)

    # The slot the doctor is already booked into.
    blocker = await _appointment(
        db, doctor, patient_user, default_clinic, at=taken
    )

    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_outside_band(3), reminder_sent=True,
    )

    # Ids captured BEFORE the commit: a commit expires the instances, and reading
    # an attribute afterwards would attempt lazy IO outside the async context.
    appointment_id = appointment.id
    blocker_id = blocker.id

    # Committed, so the appointment is as durable as it is in production. Without
    # this the rollback would discard the fixture rows and the assertion below
    # would be about the setup rather than about the flag.
    await db.commit()

    with pytest.raises(BadRequestError):
        await patient_reschedule_appointment(
            db=db,
            user=patient_user,
            appointment_id=appointment_id,
            new_datetime=taken,
        )

    await db.rollback()

    surviving = await db.scalar(
        select(Appointment.reminder_sent).where(
            Appointment.id == appointment_id
        )
    )

    assert surviving is True, (
        "a rolled-back reschedule cleared the reminder flag anyway"
    )

    # The blocker still holds the slot, which is what made the conflict real.
    assert await db.scalar(
        select(Appointment.scheduled_at).where(Appointment.id == blocker_id)
    ) == taken


@pytest.mark.asyncio
async def test_a_reschedule_rejected_before_the_write_changes_nothing(
    db, doctor, doctor_availability, patient_user, default_clinic
):
    """The other failure shape: refused by validation, so the write is never
    reached at all."""
    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_outside_band(3), reminder_sent=True,
    )

    with pytest.raises(BadRequestError):
        await patient_reschedule_appointment(
            db=db,
            user=patient_user,
            appointment_id=appointment.id,
            new_datetime=utc_now() - timedelta(days=1),
        )

    await db.refresh(appointment)

    assert appointment.reminder_sent is True


# ---------------------------------------------------------------------------
# Blast radius
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rescheduling_one_appointment_does_not_touch_another(
    db, doctor, doctor_availability, patient_user, default_clinic
):
    """Requirement 9. A bulk UPDATE that forgot its WHERE clause would re-arm
    every reminded appointment in the table."""
    untouched = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_outside_band(7), reminder_sent=True,
    )

    moving = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_outside_band(3), reminder_sent=True,
    )

    await patient_reschedule_appointment(
        db=db,
        user=patient_user,
        appointment_id=moving.id,
        new_datetime=_outside_band(4),
    )

    await db.refresh(moving)
    await db.refresh(untouched)

    assert moving.reminder_sent is False
    assert untouched.reminder_sent is True, (
        "an unrelated appointment's reminder was re-armed"
    )


@pytest.mark.asyncio
async def test_another_clinics_appointment_is_unreachable(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """Requirement 10, with a genuinely separate clinic.

    The doctor path filters its lookup on the caller's own clinic_id, so a row in
    another clinic is INVISIBLE rather than forbidden — NotFoundError, not
    ForbiddenError. Either way its reminder state cannot be disturbed.
    """
    from app.models.clinic import Clinic, ClinicStatus
    from app.models.doctor import Doctor, DoctorStatus

    other_clinic = Clinic(
        name="Other Reminder Clinic", status=ClinicStatus.ACTIVE, timezone="UTC"
    )
    db.add(other_clinic)
    await db.flush()

    other_doctor_user = User(
        email="other-clinic-doc@example.com", full_name="Other Doc",
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
        email="other-clinic-patient@example.com", full_name="Other",
        hashed_password="x", role=UserRole.PATIENT, is_active=True,
    )
    db.add(other_patient)
    await db.flush()

    db.add(Patient(
        user_id=other_patient.id, phone="+8801966000111", address="a",
        date_of_birth=utc_now().date(), gender=Gender.MALE,
    ))
    await db.flush()

    foreign = await _appointment(
        db, other_doctor, other_patient, other_clinic,
        at=_outside_band(3), reminder_sent=True,
    )

    foreign_id = foreign.id

    await db.commit()

    with pytest.raises(NotFoundError):
        await doctor_reschedule_appointment(
            db=db,
            doctor_user=doctor_user,
            appointment_id=foreign_id,
            new_datetime=_outside_band(5),
        )

    await db.rollback()

    surviving = await db.scalar(
        select(Appointment.reminder_sent).where(Appointment.id == foreign_id)
    )

    assert surviving is True


@pytest.mark.asyncio
async def test_another_doctors_appointment_in_the_same_clinic_is_refused(
    db, doctor, doctor_availability, patient_user, default_clinic,
    another_doctor, doctor_user,
):
    """The neighbouring guard: same clinic, different doctor. Visible, so it is
    ForbiddenError rather than NotFoundError — and still cannot be moved."""
    from app.try_except.exceptions import ForbiddenError

    foreign = await _appointment(
        db, another_doctor, patient_user, default_clinic,
        at=_outside_band(3), reminder_sent=True,
    )

    foreign_id = foreign.id

    await db.commit()

    with pytest.raises(ForbiddenError):
        await doctor_reschedule_appointment(
            db=db,
            doctor_user=doctor_user,
            appointment_id=foreign_id,
            new_datetime=_outside_band(5),
        )

    await db.rollback()

    surviving = await db.scalar(
        select(Appointment.reminder_sent).where(Appointment.id == foreign_id)
    )

    assert surviving is True


@pytest.mark.asyncio
async def test_the_reminder_is_still_published_only_once_after_a_reschedule(
    db, doctor, doctor_availability, patient_user, default_clinic, doctor_user
):
    """Requirement 11. Re-arming must give exactly one more reminder, not an
    unbounded stream: the flag is set again by the job's own run."""
    appointment = await _appointment(
        db, doctor, patient_user, default_clinic,
        at=_outside_band(5), reminder_sent=True,
    )

    await doctor_reschedule_appointment(
        db=db,
        doctor_user=doctor_user,
        appointment_id=appointment.id,
        new_datetime=_in_band(),
    )

    for _ in range(3):
        await _run_job(db)

    assert len(await _reminders_for(db, appointment.id)) == 1

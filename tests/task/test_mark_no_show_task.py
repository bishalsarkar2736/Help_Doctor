"""The no-show job, and the schedule that finally runs it.

mark_no_show_appointments had a test and no caller: it was absent from
beat_schedule and from every container, so CONFIRMED appointments stayed
CONFIRMED however long ago they were due.

The business logic is not retested here — the grace period and cutoff belong to
the service and tests/services/test_appointment_no_show.py covers them. What is
asserted is everything the scheduling added: that the right rows change, that
the wrong ones do not, that a second run is a no-op, that the work is COMMITTED
(the old script's was not), and that the schedule actually names a task Celery
can find.
"""

from datetime import timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import Range

from app.core.celery import celery_app
from app.core.constants import APPOINTMENT_DURATION_MINUTES
from app.core.time import utc_now
from app.models.appointment import Appointment, AppointmentStatus
from app.models.clinic import Clinic, ClinicStatus
from app.models.doctor import Doctor, DoctorStatus
from app.models.patient import Gender, Patient
from app.models.user import User, UserRole
from app.services.appointment_no_show_service import (
    NO_SHOW_GRACE_MINUTES,
    mark_no_show_appointments,
)

# Comfortably past duration + grace, so these tests never sit on the boundary
# the service owns.
OVERDUE = timedelta(minutes=APPOINTMENT_DURATION_MINUTES + NO_SHOW_GRACE_MINUTES + 30)


@pytest.fixture
async def clinic_with_doctor(db):
    clinic = Clinic(name="No Show Clinic", status=ClinicStatus.ACTIVE, timezone="UTC")
    db.add(clinic)
    await db.flush()

    user = User(
        email="noshow-doc@example.com", full_name="Dr NoShow", hashed_password="x",
        role=UserRole.DOCTOR, is_active=True, clinic_id=clinic.id,
    )
    db.add(user)
    await db.flush()

    doctor = Doctor(
        user_id=user.id, clinic_id=clinic.id, specialization="Medicine",
        experience_years=5, bio="b", status=DoctorStatus.APPROVED,
    )
    db.add(doctor)
    await db.flush()

    return {"clinic": clinic, "doctor": doctor}


_slot = 0


async def _appointment(db, ctx, *, status, due):
    """One appointment at `due`, with its own slot so the exclusion constraint
    on (doctor, time_range) never decides the outcome of a test."""
    global _slot
    _slot += 1

    patient = User(
        email=f"noshow-patient-{_slot}@example.com", full_name=f"Patient {_slot}",
        hashed_password="x", role=UserRole.PATIENT, is_active=True,
    )
    db.add(patient)
    await db.flush()

    db.add(Patient(
        user_id=patient.id, phone=f"+88018{_slot:08d}", address="a",
        date_of_birth=utc_now().date(), gender=Gender.MALE,
    ))
    await db.flush()

    appointment = Appointment(
        patient_id=patient.id,
        doctor_id=ctx["doctor"].id,
        clinic_id=ctx["clinic"].id,
        scheduled_at=due,
        status=status,
        time_range=Range(due, due + Appointment.APPOINTMENT_DURATION),
    )
    db.add(appointment)
    await db.flush()

    return appointment


# ---------------------------------------------------------------------------
# What changes, and what does not
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_overdue_confirmed_appointment_becomes_no_show(
    db, clinic_with_doctor
):
    appointment = await _appointment(
        db, clinic_with_doctor,
        status=AppointmentStatus.CONFIRMED,
        due=utc_now() - OVERDUE,
    )

    marked = await mark_no_show_appointments(db)

    assert marked == 1
    assert appointment.status == AppointmentStatus.NO_SHOW


@pytest.mark.asyncio
async def test_an_appointment_that_is_not_overdue_is_left_alone(
    db, clinic_with_doctor
):
    """Still inside its window — the patient may yet arrive."""
    appointment = await _appointment(
        db, clinic_with_doctor,
        status=AppointmentStatus.CONFIRMED,
        due=utc_now() + timedelta(hours=2),
    )

    marked = await mark_no_show_appointments(db)

    assert marked == 0
    assert appointment.status == AppointmentStatus.CONFIRMED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        AppointmentStatus.COMPLETED,
        AppointmentStatus.CANCELLED,
        AppointmentStatus.NO_SHOW,
    ],
)
async def test_settled_appointments_are_ignored(db, clinic_with_doctor, status):
    """A finished appointment is not reopened because it is old.

    COMPLETED especially: the patient attended, and rewriting that hours later
    would be inventing a clinical fact.
    """
    appointment = await _appointment(
        db, clinic_with_doctor, status=status, due=utc_now() - OVERDUE,
    )

    marked = await mark_no_show_appointments(db)

    assert marked == 0
    assert appointment.status == status


@pytest.mark.asyncio
async def test_pending_appointments_are_not_touched(db, clinic_with_doctor):
    """The service targets CONFIRMED only. A PENDING appointment was never
    accepted, so failing to attend it is not a no-show."""
    appointment = await _appointment(
        db, clinic_with_doctor,
        status=AppointmentStatus.PENDING,
        due=utc_now() - OVERDUE,
    )

    marked = await mark_no_show_appointments(db)

    assert marked == 0
    assert appointment.status == AppointmentStatus.PENDING


@pytest.mark.asyncio
async def test_only_the_overdue_one_changes_in_a_mixed_set(
    db, clinic_with_doctor
):
    """All four together, because a filter can be right about each case alone
    and still wrong about which rows it selects."""
    overdue = await _appointment(
        db, clinic_with_doctor,
        status=AppointmentStatus.CONFIRMED, due=utc_now() - OVERDUE,
    )
    upcoming = await _appointment(
        db, clinic_with_doctor,
        status=AppointmentStatus.CONFIRMED, due=utc_now() + timedelta(hours=3),
    )
    completed = await _appointment(
        db, clinic_with_doctor,
        status=AppointmentStatus.COMPLETED, due=utc_now() - OVERDUE,
    )
    cancelled = await _appointment(
        db, clinic_with_doctor,
        status=AppointmentStatus.CANCELLED, due=utc_now() - OVERDUE,
    )

    marked = await mark_no_show_appointments(db)

    assert marked == 1
    assert overdue.status == AppointmentStatus.NO_SHOW
    assert upcoming.status == AppointmentStatus.CONFIRMED
    assert completed.status == AppointmentStatus.COMPLETED
    assert cancelled.status == AppointmentStatus.CANCELLED


# ---------------------------------------------------------------------------
# Running it again
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_second_run_changes_nothing(db, clinic_with_doctor):
    """It runs every five minutes forever, so this is the normal case rather
    than an edge one.

    Idempotence comes from the query, not from the schedule: once marked, the
    row is no longer CONFIRMED and cannot be selected again.
    """
    appointment = await _appointment(
        db, clinic_with_doctor,
        status=AppointmentStatus.CONFIRMED, due=utc_now() - OVERDUE,
    )

    assert await mark_no_show_appointments(db) == 1

    marked_at = appointment.status

    assert await mark_no_show_appointments(db) == 0
    assert appointment.status == marked_at


@pytest.mark.asyncio
async def test_an_empty_run_is_fine(db, clinic_with_doctor):
    """Most runs find nothing, which must not be an error."""
    assert await mark_no_show_appointments(db) == 0


# ---------------------------------------------------------------------------
# The job wrapper — the part the scheduling adds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_job_commits_its_work(clinic_with_doctor, db):
    """The bug the old script had.

    scripts/mark_no_show.py opened a session, called the service, printed a
    count and let the context manager close — which rolls back. It reported
    marking appointments and marked none.

    Proving a commit needs REAL transactions, so this deliberately steps
    outside the rolled-back `db` fixture: the job opens its own session on its
    own connection and would see nothing written inside a savepoint. Written
    with AsyncSessionLocal and cleaned up by hand for the same reason.
    """
    from app.db.postgres import AsyncSessionLocal
    from app.task.appointment_no_show import mark_no_show_job

    due = utc_now() - OVERDUE

    async with AsyncSessionLocal() as setup:
        clinic = Clinic(
            name="Commit Proof Clinic", status=ClinicStatus.ACTIVE, timezone="UTC"
        )
        setup.add(clinic)
        await setup.flush()

        doctor_user = User(
            email="commit-proof-doc@example.com", full_name="Dr Commit",
            hashed_password="x", role=UserRole.DOCTOR, is_active=True,
            clinic_id=clinic.id,
        )
        setup.add(doctor_user)
        await setup.flush()

        doctor = Doctor(
            user_id=doctor_user.id, clinic_id=clinic.id, specialization="Medicine",
            experience_years=1, bio="b", status=DoctorStatus.APPROVED,
        )
        setup.add(doctor)

        patient = User(
            email="commit-proof-patient@example.com", full_name="Commit Patient",
            hashed_password="x", role=UserRole.PATIENT, is_active=True,
        )
        setup.add(patient)
        await setup.flush()

        setup.add(Patient(
            user_id=patient.id, phone="+8801955000111", address="a",
            date_of_birth=utc_now().date(), gender=Gender.MALE,
        ))

        appointment = Appointment(
            patient_id=patient.id, doctor_id=doctor.id, clinic_id=clinic.id,
            scheduled_at=due, status=AppointmentStatus.CONFIRMED,
            time_range=Range(due, due + Appointment.APPOINTMENT_DURATION),
        )
        setup.add(appointment)
        await setup.flush()

        appointment_id = appointment.id
        clinic_id = clinic.id
        user_ids = [doctor_user.id, patient.id]
        await setup.commit()

    try:
        marked = await mark_no_show_job()

        assert marked >= 1

        # A THIRD session: neither the one that wrote it nor the job's own.
        async with AsyncSessionLocal() as check:
            status = await check.scalar(
                select(Appointment.status).where(
                    Appointment.id == appointment_id
                )
            )

        assert status == AppointmentStatus.NO_SHOW, (
            "the job returned a count but the change was not committed"
        )
    finally:
        # Everything this test created, in foreign-key order. Committed data
        # does not roll back with the test, and leaving the clinic behind made
        # the second run collide on uq_clinic_name_lower.
        async with AsyncSessionLocal() as cleanup:
            await cleanup.execute(
                delete(Appointment).where(Appointment.clinic_id == clinic_id)
            )
            await cleanup.execute(
                delete(Patient).where(Patient.user_id.in_(user_ids))
            )
            await cleanup.execute(
                delete(Doctor).where(Doctor.clinic_id == clinic_id)
            )
            await cleanup.execute(delete(User).where(User.id.in_(user_ids)))
            await cleanup.execute(delete(Clinic).where(Clinic.id == clinic_id))
            await cleanup.commit()


@pytest.mark.asyncio
async def test_the_job_logs_what_it_did(monkeypatch, caplog):
    """Started, the count, and completed — nobody watches a five-minute job,
    so the log is the only account of whether it ran.

    run_and_log is awaited directly rather than driven through Celery: the
    task body is wrapped in @run_async, which calls asyncio.run() and raises
    inside the already-running test loop.

    The database is stubbed out because none of it is what this checks, and
    letting the job open its own session here binds pooled connections to a
    second event loop. What the other tests in this file prove about the
    database, they prove properly.
    """
    import logging

    from app.task import appointment_no_show

    async def _found_three():
        return 3

    monkeypatch.setattr(appointment_no_show, "mark_no_show_job", _found_three)

    with caplog.at_level(logging.INFO):
        marked = await appointment_no_show.run_and_log()

    assert marked == 3

    messages = [r.message for r in caplog.records]

    assert "mark_no_show_task_started" in messages
    assert "mark_no_show_task_completed" in messages

    completed = next(
        r for r in caplog.records if r.message == "mark_no_show_task_completed"
    )

    assert completed.appointments_marked == 3


@pytest.mark.asyncio
async def test_a_failure_is_logged_with_its_traceback(db, monkeypatch, caplog):
    """The fourth thing the log has to carry. A job that dies silently every
    five minutes is indistinguishable from one that finds nothing."""
    import logging

    from app.task import appointment_no_show

    async def _explode():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(appointment_no_show, "mark_no_show_job", _explode)

    with caplog.at_level(logging.INFO):
        with pytest.raises(RuntimeError):
            await appointment_no_show.run_and_log()

    failed = next(
        r for r in caplog.records if r.message == "mark_no_show_task_failed"
    )

    assert failed.levelno == logging.ERROR
    assert failed.exc_info is not None, "the traceback was not recorded"


# ---------------------------------------------------------------------------
# Evidence it will actually run
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def test_the_job_is_on_the_beat_schedule():
    """The whole defect was that this existed and nothing called it.

    Asserting the entry exists is what stops it silently falling out again.
    """
    entry = celery_app.conf.beat_schedule.get("mark-no-show-appointments")

    assert entry is not None, "the job is not scheduled"
    assert entry["schedule"] == 300.0, "expected every 5 minutes"


def test_the_scheduled_name_resolves_to_a_real_task():
    """A beat entry naming a task Celery cannot find fails at dispatch time,
    in a worker log, every five minutes — and the schedule still looks correct.

    This project registers task names that do not match their module paths
    (app.task.* modules, app.tasks.* names), so the two can drift apart without
    anything obvious being wrong.
    """
    name = celery_app.conf.beat_schedule["mark-no-show-appointments"]["task"]

    assert name in celery_app.tasks, (
        f"beat schedules {name}, which is not a registered task"
    )


def test_the_task_module_is_included_so_the_worker_registers_it():
    """include= is what makes the worker import the module at all. Without it
    the task exists in the API process and nowhere that matters."""
    assert "app.task.appointment_no_show" in celery_app.conf.include

"""System-initiated status changes do not message the patient.

A notification is the clinic speaking to a person. That fits a doctor
cancelling an appointment. It does not fit a scheduled job marking an
unattended one NO_SHOW: the patient already knows they did not attend, the
message arrives up to five minutes late, and on the first run after deployment
it arrives for every overdue appointment the clinic has ever had.

The distinction is carried on the event as `source`, not decided by event TYPE,
so the same APPOINTMENT_STATUS_CHANGED notifies when a doctor causes it and
stays quiet when the scheduler does.

WHAT MUST STILL HAPPEN
The event is published, the audit entry and status history are written, and the
clinic dashboard still refreshes. Suppressing a notification is not the same as
suppressing a record, and each of those is asserted below rather than assumed.
"""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import Range

from app.core.time import utc_now
from app.models.appointment import Appointment, AppointmentStatus
from app.models.appointment_history import AppointmentStatusHistory
from app.models.clinic import Clinic, ClinicStatus
from app.models.doctor import Doctor, DoctorStatus
from app.models.notification import Notification
from app.models.outbox_event import OutboxEvent, OutboxStatus
from app.models.patient import Gender, Patient
from app.models.user import User, UserRole
from app.schemas.event import AppointmentStatusChangedEvent
from app.schemas.event_metadata import EventSource
from app.services.appointment_no_show_service import (
    NO_SHOW_GRACE_MINUTES,
    mark_no_show_appointments,
)
from app.services.appointment_transition_service import (
    transition_appointment_locked,
)
from app.services.event_handlers.notification_handler import (
    handle_notification_event,
)
from app.core.constants import APPOINTMENT_DURATION_MINUTES

OVERDUE = timedelta(minutes=APPOINTMENT_DURATION_MINUTES + NO_SHOW_GRACE_MINUTES + 30)


@pytest.fixture
async def booked(db):
    clinic = Clinic(name="Source Clinic", status=ClinicStatus.ACTIVE, timezone="UTC")
    db.add(clinic)
    await db.flush()

    doctor_user = User(
        email="source-doc@example.com", full_name="Dr Source", hashed_password="x",
        role=UserRole.DOCTOR, is_active=True, clinic_id=clinic.id,
    )
    db.add(doctor_user)
    await db.flush()

    doctor = Doctor(
        user_id=doctor_user.id, clinic_id=clinic.id, specialization="Medicine",
        experience_years=1, bio="b", status=DoctorStatus.APPROVED,
    )
    db.add(doctor)

    patient = User(
        email="source-patient@example.com", full_name="Source Patient",
        hashed_password="x", role=UserRole.PATIENT, is_active=True,
    )
    db.add(patient)
    await db.flush()

    db.add(Patient(
        user_id=patient.id, phone="+8801944000111", address="a",
        date_of_birth=utc_now().date(), gender=Gender.MALE,
    ))
    await db.flush()

    due = utc_now() - OVERDUE
    appointment = Appointment(
        patient_id=patient.id, doctor_id=doctor.id, clinic_id=clinic.id,
        scheduled_at=due, status=AppointmentStatus.CONFIRMED,
        time_range=Range(due, due + Appointment.APPOINTMENT_DURATION),
    )
    db.add(appointment)
    await db.flush()

    return {
        "appointment": appointment,
        "doctor": doctor,
        "doctor_user": doctor_user,
        "patient": patient,
    }


def _event(source: EventSource, patient_id: int, appointment_id: int):
    return AppointmentStatusChangedEvent(
        event_type="APPOINTMENT_STATUS_CHANGED",
        schema_version=1,
        occurred_at=utc_now().isoformat(),
        aggregate_type="appointment",
        aggregate_id=appointment_id,
        source=source,
        patient_id=patient_id,
        appointment_id=appointment_id,
        doctor_id=1,
        new_status="NO_SHOW",
    )


@pytest.fixture
async def outbox_event_id(db):
    """notifications.event_id is a foreign key to outbox_events, so a
    notification cannot be written against an invented id."""
    event = OutboxEvent(
        id=uuid4(),
        event_type="APPOINTMENT_STATUS_CHANGED",
        payload={},
        status=OutboxStatus.PENDING,
    )
    db.add(event)
    await db.flush()

    return event.id


async def _notifications_for(db, user_id: int) -> int:
    return await db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user_id
        )
    )


# ---------------------------------------------------------------------------
# The handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_system_event_does_not_notify_the_patient(db, booked):
    patient_id = booked["patient"].id

    before = await _notifications_for(db, patient_id)

    await handle_notification_event(
        db=db,
        validated=_event(
            EventSource.SYSTEM, patient_id, booked["appointment"].id
        ),
        event_id=uuid4(),
        event_type="APPOINTMENT_STATUS_CHANGED",
    )

    assert await _notifications_for(db, patient_id) == before


@pytest.mark.asyncio
async def test_the_same_event_from_a_user_does_notify(db, booked, outbox_event_id):
    """The other half. Suppressing by event TYPE would have muted this too."""
    patient_id = booked["patient"].id

    before = await _notifications_for(db, patient_id)

    await handle_notification_event(
        db=db,
        validated=_event(EventSource.USER, patient_id, booked["appointment"].id),
        event_id=outbox_event_id,
        event_type="APPOINTMENT_STATUS_CHANGED",
    )

    assert await _notifications_for(db, patient_id) == before + 1


@pytest.mark.asyncio
async def test_an_event_with_no_source_still_notifies(db, booked, outbox_event_id):
    """Events queued before this field existed have no `source` key.

    They must keep behaving exactly as they did, or a schema change quietly
    mutes everything already in flight.
    """
    patient_id = booked["patient"].id

    payload = _event(
        EventSource.USER, patient_id, booked["appointment"].id
    ).model_dump()
    payload.pop("source")

    revalidated = AppointmentStatusChangedEvent.model_validate(payload)

    assert revalidated.source == EventSource.USER

    before = await _notifications_for(db, patient_id)

    await handle_notification_event(
        db=db,
        validated=revalidated,
        event_id=outbox_event_id,
        event_type="APPOINTMENT_STATUS_CHANGED",
    )

    assert await _notifications_for(db, patient_id) == before + 1


# ---------------------------------------------------------------------------
# Through the real no-show path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_no_show_job_marks_its_event_as_system(db, booked):
    marked = await mark_no_show_appointments(db)

    assert marked == 1

    event = await db.scalar(
        select(OutboxEvent)
        .where(OutboxEvent.event_type == "APPOINTMENT_STATUS_CHANGED")
        .order_by(OutboxEvent.created_at.desc())
    )

    assert event is not None, "the no-show transition published no event"
    assert event.payload["source"] == EventSource.SYSTEM.value


@pytest.mark.asyncio
async def test_a_doctor_transition_is_marked_as_user_by_default(db, booked):
    """Nine of the ten callers say nothing about source and must keep
    notifying — the default is what makes that true."""
    await transition_appointment_locked(
        db=db,
        appointment=booked["appointment"],
        new_status=AppointmentStatus.COMPLETED,
        changed_by=booked["doctor_user"].id,
        actor_role=UserRole.DOCTOR,
        emit_event=True,
    )

    event = await db.scalar(
        select(OutboxEvent)
        .where(OutboxEvent.event_type == "APPOINTMENT_STATUS_CHANGED")
        .order_by(OutboxEvent.created_at.desc())
    )

    assert event.payload["source"] == EventSource.USER.value


# ---------------------------------------------------------------------------
# Suppressing a message is not suppressing a record
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_event_is_still_published(db, booked):
    before = await db.scalar(select(func.count(OutboxEvent.id)))

    await mark_no_show_appointments(db)

    assert await db.scalar(select(func.count(OutboxEvent.id))) > before


@pytest.mark.asyncio
async def test_the_status_history_is_still_written(db, booked):
    appointment_id = booked["appointment"].id

    before = await db.scalar(
        select(func.count(AppointmentStatusHistory.id)).where(
            AppointmentStatusHistory.appointment_id == appointment_id
        )
    )

    await mark_no_show_appointments(db)

    after = await db.scalar(
        select(func.count(AppointmentStatusHistory.id)).where(
            AppointmentStatusHistory.appointment_id == appointment_id
        )
    )

    assert after == before + 1, "the audit trail lost a system transition"


@pytest.mark.asyncio
async def test_the_appointment_is_still_marked(db, booked):
    """The business rule is untouched by any of this."""
    await mark_no_show_appointments(db)

    assert booked["appointment"].status == AppointmentStatus.NO_SHOW


@pytest.mark.asyncio
async def test_the_clinic_dashboard_still_refreshes(db, booked, monkeypatch):
    """A board going stale would be a real regression, and it is not a patient
    notification."""
    from app.services.event_handlers import notification_handler

    refreshed = []

    async def _record(*, db, clinic_id):
        refreshed.append(clinic_id)

    monkeypatch.setattr(
        notification_handler, "publish_dashboard_update", _record
    )

    await handle_notification_event(
        db=db,
        validated=_event(
            EventSource.SYSTEM,
            booked["patient"].id,
            booked["appointment"].id,
        ),
        event_id=outbox_event_id,
        event_type="APPOINTMENT_STATUS_CHANGED",
    )

    assert refreshed == [booked["appointment"].clinic_id]

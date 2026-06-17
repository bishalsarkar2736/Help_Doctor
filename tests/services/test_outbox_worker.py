
import pytest
from sqlalchemy import select
from unittest.mock import AsyncMock
from datetime import datetime

from app.core.time import UTC
from app.workers.outbox_worker import process_batch
from app.models.outbox_event import OutboxEvent
from app.models.notification import Notification
from app.models.user import User, UserRole
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.appointment import Appointment
from app.websocket.manager import manager
from datetime import timedelta
from sqlalchemy.dialects.postgresql import Range
from app.models.notification_preference import (
    NotificationPreference,
)




@pytest.mark.asyncio
async def test_outbox_event_creates_notification(db):

    # -----------------------------
    # Create user
    # -----------------------------
    patient_user = User(
        email="patient@test.com",
        hashed_password="fakehash",
        role=UserRole.PATIENT,
    )

    db.add(patient_user)
    await db.flush()

    # doctor user
    doctor_user = User(
        email="doctor_outbox@test.com",
        hashed_password="hash",
        role=UserRole.DOCTOR,
    )
    db.add(doctor_user)
    await db.flush()

    db.add(
        NotificationPreference(
            user_id=patient_user.id,
            realtime_enabled=True,
            push_enabled=True,
        )
    )
    await db.flush()

    # doctor
    doctor = Doctor(
        user_id=doctor_user.id,
        specialization="Cardiology",
        experience_years=5,
        bio="Test doctor",
        is_verified=True,
    )
    db.add(doctor)
    await db.flush()

    # patient
    patient = Patient(
            user_id=patient_user.id,
            phone="01700000000",
            address="Rangpur",
            date_of_birth="1995-01-01",
            gender="male",
    )
    db.add(patient)
    await db.flush()


    # -----------------------------
    # Create appointment
    # -----------------------------
    start = datetime.now(UTC)

    appointment = Appointment(
        patient_id=patient_user.id,
        doctor_id=doctor.id,
        scheduled_at=start,
        status="PENDING",
        time_range=Range(start, start + timedelta(minutes=30)),
    )

    db.add(appointment)
    await db.flush()

    # -----------------------------
    # Create outbox event
    # -----------------------------
    event = OutboxEvent(
        event_type="APPOINTMENT_STATUS_CHANGED",
        payload={
            "event_type": "APPOINTMENT_STATUS_CHANGED",

            "schema_version": 1,
            "occurred_at": datetime.now(UTC).isoformat(),

            # NEW REQUIRED FIELDS
            "aggregate_type": "appointment",
            "aggregate_id": appointment.id,

            # OPTIONAL BUT RECOMMENDED
            "correlation_id": None,
            "causation_id": None,

            # actor metadata
            "actor": {
                "id": patient_user.id,
                "role": patient_user.role.name,
            },

            # domain payload
            "appointment_id": appointment.id,
            "new_status": "CONFIRMED",
            "patient_id": patient_user.id,
            "doctor_id": doctor.id,
            "changed_by": patient_user.id,
        },
    )

    db.add(event)
    await db.flush()

    await db.commit()

    # -----------------------------
    # Mock websocket
    # -----------------------------
    manager.notify_user = AsyncMock()

    # -----------------------------
    # Run worker
    # -----------------------------
    processed = await process_batch(db)

    assert processed >= 1

    # -----------------------------
    # Check notification
    # -----------------------------
    # result = await db.execute(select(Notification))
    # notification = result.scalar_one()

    result = await db.execute(
        select(Notification).where(
            Notification.event_id == event.id,
            Notification.user_id == patient_user.id,
        )
    )
    notifications = result.scalars().all()

    assert len(notifications) == 1

    for n in notifications:
        print(n.title, n.message)

    notification = notifications[0]

    assert notification.user_id == patient_user.id
    assert "CONFIRMED" in notification.message

    # -----------------------------
    # Check event processed
    # -----------------------------
    # result = await db.execute(select(OutboxEvent))
    # stored_event = result.scalar_one()

    result = await db.execute(
        select(OutboxEvent).where(
            OutboxEvent.id == event.id
        )
    )
    stored_event = result.scalar_one()

    assert stored_event.status == "processed"
    assert stored_event.processed_at is not None

    # -----------------------------
    # Websocket triggered
    # -----------------------------
    calls = manager.notify_user.await_args_list

    

    # assert any(
    #     (
    #         call.kwargs.get("user_id") == patient_user.id
    #         and call.kwargs.get("appointment_id") == appointment.id
    #         and call.kwargs.get("message", {}).get("event")
    #             == "appointment_status_changed"
    #     )
    #     or
    #     (
    #         len(call.args) >= 2
    #         and call.args[0] == patient_user.id
    #     )
    #     for call in calls
    # )
    print(manager.notify_user.await_args_list)

    assert any(
        call.kwargs.get("user_id")
            == patient_user.id
        and
        call.kwargs.get(
            "message", {}
        ).get("event")
            == "appointment_status_changed"
        and
        call.kwargs.get(
            "message", {}
        ).get("appointment_id")
            == appointment.id
        for call in calls
    )
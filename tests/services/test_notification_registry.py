"""The three event registries must agree, or notifications vanish silently.

An event has to appear in three places to reach anybody:

    EVENT_SCHEMAS               so the outbox worker can validate the payload
    EVENT_HANDLERS             so the dispatcher routes it
    EVENT_NOTIFICATION_CONFIG  so the handler knows what to send and to whom

Nothing enforced that, and two events were each missing one entry. Both failed
without a trace — no exception, no dead letter, the outbox row marked processed:

  PAYMENT_REFUNDED had a schema and a written message but no handler, so
  dispatch_event returned and a refunded patient was never told.

  APPOINTMENT_RESCHEDULE_REQUEST had a handler and a message but no schema, so
  the worker logged "skipping_unsupported_event" and a doctor never learned a
  patient had asked to move an appointment.

The end-to-end tests below go through handle_event — the function that was doing
the dropping — rather than calling the notification handler directly, because
calling the handler directly is exactly the test that would have passed while
both features were broken.
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
from app.models.patient import Gender, Patient
from app.models.outbox_event import OutboxEvent, OutboxStatus
from app.models.user import User, UserRole
from app.schemas.event_registry import EVENT_SCHEMAS
from app.services.event_handlers.dispatcher import EVENT_HANDLERS
from app.services.event_handlers.notification_handler import (
    EVENT_NOTIFICATION_CONFIG,
)
from app.workers.outbox_worker import handle_event

# In EVENT_SCHEMAS and configured, but no code constructs it. Harmless — a
# schema with no publisher drops nothing — and completion already notifies via
# APPOINTMENT_STATUS_CHANGED, so publishing it too would notify twice. Listed
# so the state is deliberate rather than unnoticed, and so a SECOND dead entry
# appearing fails the test below.
KNOWN_UNPUBLISHED = {"CONSULTATION_COMPLETED"}


def _published_event_types() -> dict[str, set[str]]:
    """Every event_type literal constructed in app code."""
    import pathlib
    import re

    found: dict[str, set[str]] = {}

    for path in pathlib.Path("app").rglob("*.py"):
        if "schemas/event" in str(path) or "event_registry" in str(path):
            continue

        for match in re.finditer(
            r'event_type\s*=\s*"([A-Z_]+)"', path.read_text()
        ):
            found.setdefault(match.group(1), set()).add(str(path))

    return found


# ---------------------------------------------------------------------------
# The four ways the registries can disagree
# ---------------------------------------------------------------------------


def test_every_published_event_has_a_schema():
    """Missing here, the worker marks the row processed and returns. The event
    is destroyed rather than retried — this is the failure that hid
    APPOINTMENT_RESCHEDULE_REQUEST."""
    missing = {
        event_type: sorted(paths)
        for event_type, paths in _published_event_types().items()
        if event_type not in EVENT_SCHEMAS
    }

    assert not missing, (
        "published but absent from EVENT_SCHEMAS, so the outbox worker will "
        f"silently discard these: {missing}"
    )


def test_every_schema_has_a_handler():
    """A validated event with nowhere to go is dispatch_event returning None."""
    missing = sorted(et for et in EVENT_SCHEMAS if et not in EVENT_HANDLERS)

    assert not missing, (
        f"in EVENT_SCHEMAS but absent from EVENT_HANDLERS: {missing}"
    )


def test_every_notification_handler_has_configuration():
    """Routed to the notification handler with no config, handle_notification_event
    returns at `if not config`. The event looks handled and sends nothing."""
    missing = sorted(
        event_type
        for event_type, handler in EVENT_HANDLERS.items()
        if getattr(handler, "__name__", "") == "handle_notification_event"
        and event_type not in EVENT_NOTIFICATION_CONFIG
    )

    assert not missing, (
        f"dispatched to the notification handler with no notification "
        f"configured: {missing}"
    )


def test_every_configured_notification_has_a_handler_and_a_schema():
    """Configuration alone sends nothing. This is the failure that hid
    PAYMENT_REFUNDED: a written message, and no route to it."""
    unrouted = sorted(
        et for et in EVENT_NOTIFICATION_CONFIG if et not in EVENT_HANDLERS
    )
    unvalidated = sorted(
        et for et in EVENT_NOTIFICATION_CONFIG if et not in EVENT_SCHEMAS
    )

    assert not unrouted, f"configured but no handler: {unrouted}"
    assert not unvalidated, f"configured but no schema: {unvalidated}"


def test_configuration_fields_exist_on_the_event():
    """A config naming a field the event lacks is an AttributeError at delivery
    time, in a worker log, for one event type only."""
    import re

    problems = []

    for event_type, config in EVENT_NOTIFICATION_CONFIG.items():
        schema = EVENT_SCHEMAS.get(event_type)

        if schema is None:
            continue

        fields = set(schema.model_fields)

        for key in ("user_field", "appointment_field"):
            if config[key] not in fields:
                problems.append(f"{event_type}.{config[key]} ({key})")

        for placeholder in re.findall(
            r"\{(\w+)\}", config.get("message_template", "")
        ):
            if placeholder not in fields:
                problems.append(f"{event_type} template {{{placeholder}}}")

    assert not problems, f"notification config references missing fields: {problems}"


def test_the_only_unpublished_schema_is_the_known_one():
    """A schema nobody publishes is harmless, but a second one appearing means
    somebody registered an event and forgot to emit it."""
    published = set(_published_event_types())

    unpublished = {et for et in EVENT_SCHEMAS if et not in published}

    assert unpublished == KNOWN_UNPUBLISHED, (
        f"unpublished event schemas changed: {sorted(unpublished)}"
    )


# ---------------------------------------------------------------------------
# End to end, through the worker that was dropping them
# ---------------------------------------------------------------------------


@pytest.fixture
async def two_users(db):
    """Three people and one real appointment.

    notifications.related_appointment_id is a foreign key, so the
    appointment_id in these payloads has to exist — an invented one aborts the
    transaction rather than failing the assertion.
    """
    clinic = Clinic(
        name="Registry Clinic", status=ClinicStatus.ACTIVE, timezone="UTC"
    )
    db.add(clinic)
    await db.flush()

    patient = User(
        email="registry-patient@example.com", full_name="Registry Patient",
        hashed_password="x", role=UserRole.PATIENT, is_active=True,
    )
    doctor_user = User(
        email="registry-doctor@example.com", full_name="Registry Doctor",
        hashed_password="x", role=UserRole.DOCTOR, is_active=True,
        clinic_id=clinic.id,
    )
    admin = User(
        email="registry-admin@example.com", full_name="Registry Admin",
        hashed_password="x", role=UserRole.ADMIN, is_active=True,
        clinic_id=clinic.id,
    )
    db.add_all([patient, doctor_user, admin])
    await db.flush()

    db.add(Patient(
        user_id=patient.id, phone="+8801922000111", address="a",
        date_of_birth=utc_now().date(), gender=Gender.MALE,
    ))

    doctor = Doctor(
        user_id=doctor_user.id, clinic_id=clinic.id, specialization="Medicine",
        experience_years=1, bio="b", status=DoctorStatus.APPROVED,
    )
    db.add(doctor)
    await db.flush()

    start = utc_now() + timedelta(days=1)
    appointment = Appointment(
        patient_id=patient.id, doctor_id=doctor.id, clinic_id=clinic.id,
        scheduled_at=start, status=AppointmentStatus.CONFIRMED,
        time_range=Range(start, start + Appointment.APPOINTMENT_DURATION),
    )
    db.add(appointment)
    await db.flush()

    return {
        "patient": patient,
        "doctor": doctor_user,
        "admin": admin,
        "appointment_id": appointment.id,
    }


async def _queue(db, event_type: str, payload: dict) -> OutboxEvent:
    event = OutboxEvent(
        id=uuid.uuid4(),
        event_type=event_type,
        payload=payload,
        status=OutboxStatus.PENDING,
    )
    db.add(event)
    await db.flush()
    return event


async def _notifications(db, user_id: int) -> list[Notification]:
    return list(
        (
            await db.scalars(
                select(Notification).where(Notification.user_id == user_id)
            )
        ).all()
    )


def _base(aggregate_type: str, aggregate_id: int) -> dict:
    return {
        "schema_version": 1,
        "occurred_at": utc_now().isoformat(),
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "correlation_id": str(uuid.uuid4()),
    }


@pytest.mark.asyncio
async def test_a_refund_notifies_the_patient(db, two_users):
    """Delivered at all — and to the right person.

    The event was published with user_id=refunded_by.id, so wiring the handler
    alone would have told the ADMINISTRATOR their own payment was refunded.
    """
    payload = {
        **_base("payment", two_users["appointment_id"]),
        "event_type": "PAYMENT_REFUNDED",
        "user_id": two_users["patient"].id,
        "appointment_id": two_users["appointment_id"],
        "payment_id": 1,
        "refund_transaction_id": "rtx-1",
        "refunded_amount": "500.00",
    }

    event = await _queue(db, "PAYMENT_REFUNDED", payload)

    await handle_event(db, event)

    received = await _notifications(db, two_users["patient"].id)

    assert len(received) == 1, "the refunded patient was not notified"
    assert "500.00" in received[0].message
    assert "refunded" in received[0].message.lower()

    assert await _notifications(db, two_users["admin"].id) == [], (
        "the administrator was notified instead of, or as well as, the patient"
    )

    # Status is not asserted: handle_event delivers, and process_batch marks the
    # row. Notably the OLD missing-schema branch DID set "processed" itself, so
    # status was never able to tell a handled event from a discarded one — the
    # notification is the only evidence that distinguishes them.


@pytest.mark.asyncio
async def test_a_reschedule_request_notifies_the_doctor(db, two_users):
    """The recipient is the doctor: the event carries user_id=doctor.user_id and
    the message reads "A patient requested to reschedule an appointment"."""
    payload = {
        **_base("appointment", two_users["appointment_id"]),
        "event_type": "APPOINTMENT_RESCHEDULE_REQUEST",
        "user_id": two_users["doctor"].id,
        "appointment_id": two_users["appointment_id"],
    }

    event = await _queue(db, "APPOINTMENT_RESCHEDULE_REQUEST", payload)

    await handle_event(db, event)

    received = await _notifications(db, two_users["doctor"].id)

    assert len(received) == 1, "the doctor was not notified of the request"
    assert "reschedule" in received[0].message.lower()

    assert await _notifications(db, two_users["patient"].id) == [], (
        "the patient was notified of their own request"
    )

    # Status is not asserted: handle_event delivers, and process_batch marks the
    # row. Notably the OLD missing-schema branch DID set "processed" itself, so
    # status was never able to tell a handled event from a discarded one — the
    # notification is the only evidence that distinguishes them.


@pytest.mark.asyncio
async def test_the_reschedule_request_is_no_longer_skipped(db, two_users):
    """Specifically that it is not dropped by the missing-schema branch.

    That branch marks the row processed too, so status alone cannot tell the
    two apart — the notification is what distinguishes handled from discarded.
    """
    payload = {
        **_base("appointment", two_users["appointment_id"]),
        "event_type": "APPOINTMENT_RESCHEDULE_REQUEST",
        "user_id": two_users["doctor"].id,
        "appointment_id": two_users["appointment_id"],
    }

    event = await _queue(db, "APPOINTMENT_RESCHEDULE_REQUEST", payload)

    await handle_event(db, event)

    assert await db.scalar(
        select(func.count(Notification.id)).where(
            Notification.event_id == event.id
        )
    ) == 1


# ---------------------------------------------------------------------------
# Retry and de-duplication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type, extra",
    [
        (
            "PAYMENT_REFUNDED",
            {
                "payment_id": 2,
                "refund_transaction_id": "rtx-2",
                "refunded_amount": "250.00",
            },
        ),
        ("APPOINTMENT_RESCHEDULE_REQUEST", {}),
    ],
)
async def test_reprocessing_the_same_event_does_not_notify_twice(
    db, two_users, event_type, extra
):
    """The outbox is at-least-once: acks_late means a worker that dies after
    delivering redelivers the same row.

    De-duplication is the unique constraint on (event_id, user_id) plus
    on_conflict_do_nothing in create_notification. These two event types now
    reach that path for the first time, so it is worth proving they land on it
    rather than assuming.
    """
    recipient = (
        two_users["patient"]
        if event_type == "PAYMENT_REFUNDED"
        else two_users["doctor"]
    )

    payload = {
        **_base("payment" if extra else "appointment", two_users["appointment_id"]),
        "event_type": event_type,
        "user_id": recipient.id,
        "appointment_id": two_users["appointment_id"],
        **extra,
    }

    event = await _queue(db, event_type, payload)

    await handle_event(db, event)
    await handle_event(db, event)
    await handle_event(db, event)

    assert len(await _notifications(db, recipient.id)) == 1, (
        "redelivery produced duplicate notifications"
    )


@pytest.mark.asyncio
async def test_two_recipients_of_one_event_are_not_deduplicated(db, two_users):
    """The constraint is on (event_id, user_id), not event_id alone.

    Booking and cancellation publish one event per audience, so collapsing on
    event_id would silence one of the two.
    """
    for recipient in (two_users["patient"], two_users["doctor"]):
        payload = {
            **_base("appointment", two_users["appointment_id"]),
            "event_type": "APPOINTMENT_RESCHEDULE_REQUEST",
            "user_id": recipient.id,
            "appointment_id": two_users["appointment_id"],
        }
        event = await _queue(db, "APPOINTMENT_RESCHEDULE_REQUEST", payload)
        await handle_event(db, event)

    assert len(await _notifications(db, two_users["patient"].id)) == 1
    assert len(await _notifications(db, two_users["doctor"].id)) == 1


@pytest.mark.asyncio
async def test_an_unchanged_event_type_still_behaves(db, two_users):
    """Guard on "do not change unrelated notification behaviour"."""
    payload = {
        **_base("appointment", two_users["appointment_id"]),
        "event_type": "APPOINTMENT_CANCELLED",
        "user_id": two_users["patient"].id,
        "appointment_id": two_users["appointment_id"],
        "cancelled_by": {"id": two_users["doctor"].id, "role": "DOCTOR"},
        "reason": "clinic closed",
    }

    event = await _queue(db, "APPOINTMENT_CANCELLED", payload)

    await handle_event(db, event)

    assert len(await _notifications(db, two_users["patient"].id)) == 1


# ---------------------------------------------------------------------------
# The recipient, asserted where it is decided
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_real_refund_addresses_the_event_to_the_patient(
    client, db, default_clinic, auth_doctor
):
    """Asserted at the PUBLICATION site, not on a hand-written payload.

    The end-to-end tests above supply user_id themselves, so they prove the
    handler delivers to whoever the event names — and would keep passing if the
    event named the wrong person. It did: refund_payment set
    user_id=refunded_by.id, the administrator issuing the refund.

    Reverting that line fails this test and nothing else, which is exactly why
    it is here.
    """
    from tests.api.test_payment_refund import (
        create_success_payment,
        mock_bkash_refund,
    )

    payment = await create_success_payment(
        db=db, default_clinic=default_clinic, doctor=auth_doctor["doctor"]
    )

    patient_user_id = payment.patient_id
    refunding_admin_id = auth_doctor["user"].id

    with mock_bkash_refund():
        response = await client.post(
            f"/payments/{payment.id}/refund",
            json={"amount": "100", "reason": "Patient requested refund"},
            headers=auth_doctor["headers"],
        )

    assert response.status_code == 200, response.text

    event = await db.scalar(
        select(OutboxEvent)
        .where(OutboxEvent.event_type == "PAYMENT_REFUNDED")
        .order_by(OutboxEvent.created_at.desc())
    )

    assert event is not None, "the refund published no event"

    assert event.payload["user_id"] == patient_user_id, (
        "the refund notification is addressed to "
        f"{event.payload['user_id']}, not the patient ({patient_user_id})"
    )

    assert event.payload["user_id"] != refunding_admin_id, (
        "addressed to whoever processed the refund"
    )

    # The actor still records who issued it — the fix moved the recipient, it
    # did not lose the attribution.
    assert event.payload["actor"]["id"] == refunding_admin_id

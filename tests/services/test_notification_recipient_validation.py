"""A notification only goes to someone the event is about.

Nothing checked this. The handler delivered to whatever user id the event
named, so a publisher naming the wrong person produced a correctly formatted
message sent to a stranger. That is not hypothetical: PAYMENT_REFUNDED
addressed "Your payment has been refunded" to the administrator who issued the
refund, and wiring the handler up was not enough to catch it.

The rule is that the recipient must be a party to the event's appointment — its
patient, or its doctor. That makes the clinic check structural rather than a
comparison: both parties are of that appointment's clinic by construction, so a
user from another clinic cannot be in the allowed set. Comparing clinic ids
would have been meaningless for a patient anyway, since patients are global and
belong to every clinic that has treated them.

Which of the two is acceptable comes from the configuration's user_field,
because one event type serves two audiences — booking, confirmation and
cancellation each publish to the patient AND the doctor under the same type.
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
from app.models.outbox_event import OutboxEvent
from app.models.patient import Gender, Patient
from app.models.user import User, UserRole
from app.services.event_handlers.notification_handler import (
    RecipientNotPartyToEvent,
    handle_notification_event,
)


async def _clinic_with_appointment(db, tag: str):
    clinic = Clinic(
        name=f"Recipient {tag}", status=ClinicStatus.ACTIVE, timezone="UTC"
    )
    db.add(clinic)
    await db.flush()

    doctor_user = User(
        email=f"rv-doc-{tag}@example.com", full_name=f"Dr {tag}",
        hashed_password="x", role=UserRole.DOCTOR, is_active=True,
        clinic_id=clinic.id,
    )
    admin = User(
        email=f"rv-admin-{tag}@example.com", full_name=f"Admin {tag}",
        hashed_password="x", role=UserRole.ADMIN, is_active=True,
        clinic_id=clinic.id,
    )
    patient_user = User(
        email=f"rv-pat-{tag}@example.com", full_name=f"Patient {tag}",
        hashed_password="x", role=UserRole.PATIENT, is_active=True,
    )
    db.add_all([doctor_user, admin, patient_user])
    await db.flush()

    doctor = Doctor(
        user_id=doctor_user.id, clinic_id=clinic.id, specialization="Medicine",
        experience_years=1, bio="b", status=DoctorStatus.APPROVED,
    )
    db.add(doctor)

    db.add(Patient(
        user_id=patient_user.id, phone=f"+88019{abs(hash(tag)) % 100000000:08d}",
        address="a", date_of_birth=utc_now().date(), gender=Gender.MALE,
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
        "admin": admin,
        "patient": patient_user,
        "appointment": appointment,
    }


@pytest.fixture
async def two_clinics(db):
    return {
        "A": await _clinic_with_appointment(db, "A"),
        "B": await _clinic_with_appointment(db, "B"),
    }


async def _deliver(db, event_type: str, payload: dict):
    """Through the handler, with a real outbox row for the FK."""
    event = OutboxEvent(
        id=uuid.uuid4(), event_type=event_type, payload=payload, status="PENDING"
    )
    db.add(event)
    await db.flush()

    class _Validated:
        def __init__(self, data):
            self.__dict__.update(data)

        def model_dump(self):
            return dict(self.__dict__)

    await handle_notification_event(
        db=db,
        validated=_Validated(payload),
        event_id=event.id,
        event_type=event_type,
    )

    return event


def _payload(ctx, *, recipient_id, extra=None):
    data = {
        "correlation_id": str(uuid.uuid4()),
        "appointment_id": ctx["appointment"].id,
        "user_id": recipient_id,
        "patient_id": recipient_id,
        "source": None,
    }
    data.update(extra or {})
    return data


async def _count(db, user_id):
    return await db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user_id
        )
    )


# ---------------------------------------------------------------------------
# The parties are accepted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_appointments_patient_is_accepted(db, two_clinics):
    a = two_clinics["A"]

    await _deliver(
        db, "APPOINTMENT_CANCELLED",
        _payload(a, recipient_id=a["patient"].id, extra={
            "cancelled_by": {"id": a["doctor_user"].id, "role": "DOCTOR"},
            "reason": "x",
        }),
    )

    assert await _count(db, a["patient"].id) == 1


@pytest.mark.asyncio
async def test_the_appointments_doctor_is_accepted(db, two_clinics):
    """The fan-out addresses the doctor under the same event type, so the
    doctor has to be acceptable too."""
    a = two_clinics["A"]

    await _deliver(
        db, "APPOINTMENT_CANCELLED",
        _payload(a, recipient_id=a["doctor_user"].id, extra={
            "cancelled_by": {"id": a["doctor_user"].id, "role": "DOCTOR"},
            "reason": "x",
        }),
    )

    assert await _count(db, a["doctor_user"].id) == 1


@pytest.mark.asyncio
async def test_a_patient_addressed_event_reaches_the_patient(db, two_clinics):
    a = two_clinics["A"]

    await _deliver(
        db, "PRESCRIPTION_ISSUED",
        _payload(a, recipient_id=a["patient"].id, extra={"prescription_id": 1}),
    )

    assert await _count(db, a["patient"].id) == 1


# ---------------------------------------------------------------------------
# Wrong person, same clinic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_administrator_of_the_same_clinic_is_refused(db, two_clinics):
    """The shape of the real PAYMENT_REFUNDED bug.

    The admin belongs to the appointment's clinic, so a clinic-id comparison
    would have waved this through. They are not a party to the appointment, and
    the message says "Your payment has been refunded".
    """
    a = two_clinics["A"]

    with pytest.raises(RecipientNotPartyToEvent):
        await _deliver(
            db, "PAYMENT_REFUNDED",
            _payload(a, recipient_id=a["admin"].id, extra={
                "payment_id": 1,
                "refund_transaction_id": "t",
                "refunded_amount": "500.00",
            }),
        )

    assert await _count(db, a["admin"].id) == 0


@pytest.mark.asyncio
async def test_a_doctor_is_refused_a_patient_addressed_message(db, two_clinics):
    """user_field is patient_id, so only the patient will do — even though the
    doctor IS a party to the appointment.

    "Your prescription is ready" sent to the prescriber is not a notification,
    it is a bug with good grammar.
    """
    a = two_clinics["A"]

    with pytest.raises(RecipientNotPartyToEvent):
        await _deliver(
            db, "PRESCRIPTION_ISSUED",
            _payload(a, recipient_id=a["doctor_user"].id,
                     extra={"prescription_id": 1}),
        )

    assert await _count(db, a["doctor_user"].id) == 0


# ---------------------------------------------------------------------------
# Wrong clinic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["patient", "doctor_user", "admin"])
async def test_nobody_from_another_clinic_is_accepted(db, two_clinics, who):
    """Clinic A's appointment cannot notify any of Clinic B's people.

    Reproduced before this existed: the handler delivered happily.
    """
    a, b = two_clinics["A"], two_clinics["B"]

    with pytest.raises(RecipientNotPartyToEvent):
        await _deliver(
            db, "APPOINTMENT_CANCELLED",
            _payload(a, recipient_id=b[who].id, extra={
                "cancelled_by": {"id": a["doctor_user"].id, "role": "DOCTOR"},
                "reason": "x",
            }),
        )

    assert await _count(db, b[who].id) == 0


@pytest.mark.asyncio
async def test_another_clinics_patient_is_refused(db, two_clinics):
    """Patients are global, so a clinic-id comparison would say nothing about
    them at all. Being a party to THIS appointment does."""
    a, b = two_clinics["A"], two_clinics["B"]

    with pytest.raises(RecipientNotPartyToEvent):
        await _deliver(
            db, "APPOINTMENT_STATUS_CHANGED",
            _payload(a, recipient_id=b["patient"].id,
                     extra={"new_status": "CONFIRMED", "doctor_id": 1}),
        )

    assert await _count(db, b["patient"].id) == 0


# ---------------------------------------------------------------------------
# Nothing is delivered on rejection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_rejected_recipient_gets_no_record_at_all(db, two_clinics):
    """The check runs before the message is built, so there is nothing to
    half-send."""
    a = two_clinics["A"]

    before = await db.scalar(select(func.count(Notification.id)))

    with pytest.raises(RecipientNotPartyToEvent):
        await _deliver(
            db, "PAYMENT_SUCCESS",
            _payload(a, recipient_id=a["admin"].id),
        )

    assert await db.scalar(select(func.count(Notification.id))) == before


# ---------------------------------------------------------------------------
# Fail open only where verification is impossible
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_event_without_an_appointment_is_not_rejected(db, two_clinics):
    """Verification is impossible without an appointment, so it is skipped and
    logged rather than treated as a bad recipient.

    Not reachable through any current event — every schema requires
    appointment_id — but the branch decides what happens if one ever omits it,
    and refusing to deliver would be the wrong answer to "we could not check".
    """
    a = two_clinics["A"]

    payload = _payload(a, recipient_id=a["patient"].id)
    payload["appointment_id"] = None

    await _deliver(db, "APPOINTMENT_CONFIRMED", payload)

    assert await _count(db, a["patient"].id) == 1


@pytest.mark.asyncio
async def test_a_nonexistent_appointment_is_stopped_by_the_foreign_key(
    db, two_clinics
):
    """Recording the real behaviour, which is not what the fail-open branch
    suggests on its own.

    notifications.related_appointment_id references appointments, so an
    appointment id that does not exist cannot produce a notification whatever
    this validation decides. The validator skips (it cannot check), and the
    insert then fails on the foreign key — an IntegrityError, not a
    RecipientNotPartyToEvent.

    Worth pinning because the two failures mean different things and only one
    of them indicates a mis-addressed message.
    """
    from sqlalchemy.exc import IntegrityError

    a = two_clinics["A"]

    payload = _payload(a, recipient_id=a["patient"].id)
    payload["appointment_id"] = 987654

    with pytest.raises(IntegrityError):
        await _deliver(db, "APPOINTMENT_CONFIRMED", payload)


# ---------------------------------------------------------------------------
# Unchanged behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_system_event_is_still_suppressed_not_rejected(db, two_clinics):
    """SYSTEM suppression and recipient validation are different questions.

    A valid recipient on a system-initiated event must still produce no patient
    notification, and must not raise.
    """
    from app.schemas.event_metadata import EventSource

    a = two_clinics["A"]

    payload = _payload(a, recipient_id=a["patient"].id,
                       extra={"new_status": "NO_SHOW", "doctor_id": 1})
    payload["source"] = EventSource.SYSTEM

    await _deliver(db, "APPOINTMENT_STATUS_CHANGED", payload)

    assert await _count(db, a["patient"].id) == 0


@pytest.mark.asyncio
async def test_delivery_channels_are_untouched(db, two_clinics):
    """A valid recipient still goes through the ordinary path: a record, and
    the preference-gated channels behind it."""
    a = two_clinics["A"]

    await _deliver(
        db, "PATIENT_NEXT_IN_QUEUE",
        _payload(a, recipient_id=a["patient"].id, extra={"doctor_id": 1}),
    )

    stored = await db.scalar(
        select(Notification).where(Notification.user_id == a["patient"].id)
    )

    assert stored is not None
    assert stored.read_at is None
    assert stored.seen_at is None

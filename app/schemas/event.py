from pydantic import BaseModel, ConfigDict
from typing import Literal
from app.schemas.event_metadata import EventMetadata

class BaseEvent(EventMetadata):

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )


# =========================
# COMMON NESTED MODELS
# =========================
class CancelledByInfo(BaseModel):

    id: int
    role: str

    


# =========================
# APPOINTMENT CREATED
# =========================
class AppointmentCreatedEvent(BaseEvent):

    event_type: Literal[
        "APPOINTMENT_CREATED"
    ]

    user_id: int
    appointment_id: int
    doctor_id: int
    scheduled_at: str


# =========================
# APPOINTMENT CONFIRMED
# =========================
class AppointmentConfirmedEvent(BaseEvent):

    event_type: Literal[
        "APPOINTMENT_CONFIRMED"
    ]


    user_id: int
    appointment_id: int


# =========================
# APPOINTMENT CANCELLED
# =========================
class AppointmentCancelledEvent(BaseEvent):

    event_type: Literal[
        "APPOINTMENT_CANCELLED"
    ]

    user_id: int
    appointment_id: int

    cancelled_by: CancelledByInfo

    reason: str = ""


# =========================
# APPOINTMENT RESCHEDULED
# =========================
class AppointmentRescheduledEvent(BaseEvent):

    event_type: Literal[
        "APPOINTMENT_RESCHEDULED"
    ]

    user_id: int
    appointment_id: int


# =========================
# APPOINTMENT REMINDER
# =========================
class AppointmentReminderEvent(BaseEvent):
    """The scheduled nudge before an appointment.

    Registered here so the outbox worker recognises it. It was previously
    published as the raw string "appointment.reminder", which normalises to
    APPOINTMENT.REMINDER, matches nothing in EVENT_SCHEMAS, and was therefore
    marked processed and dropped on every run.

    Deliberately the same minimal shape as its siblings: the recipient and the
    appointment, and nothing else. The doctor, the time and the clinic's timezone
    are read from the appointment aggregate when a message is built, so a name
    that changes later cannot be frozen into an immutable event.
    """

    event_type: Literal[
        "APPOINTMENT_REMINDER"
    ]

    user_id: int
    appointment_id: int


# =========================
# APPOINTMENT RESCHEDULE REQUEST
# =========================
class AppointmentRescheduleRequestEvent(BaseEvent):

    event_type: Literal[
        "APPOINTMENT_RESCHEDULE_REQUEST"
    ]

    user_id: int
    appointment_id: int


# =========================
# STATUS CHANGED
# =========================
class AppointmentStatusChangedEvent(BaseEvent):

    event_type: Literal[
        "APPOINTMENT_STATUS_CHANGED"
    ]

    patient_id: int
    appointment_id: int
    doctor_id: int

    changed_by: int | None = None
    new_status: str


class PatientNextInQueueEvent(BaseEvent):

    event_type: Literal[
        "PATIENT_NEXT_IN_QUEUE"
    ]

    patient_id: int
    appointment_id: int
    doctor_id: int


class ConsultationStartedEvent(BaseEvent):

    event_type: Literal[
        "CONSULTATION_STARTED"
    ]

    appointment_id: int
    patient_id: int
    doctor_id: int


class ConsultationCompletedEvent(BaseEvent):

    event_type: Literal["CONSULTATION_COMPLETED"]

    patient_id: int
    appointment_id: int
    doctor_id: int
    

# =========================
# PAYMENT SUCCESS
# =========================
class PaymentSuccessEvent(BaseEvent):

    event_type: Literal[
        "PAYMENT_SUCCESS"
    ]

    user_id: int
    appointment_id: int


class PaymentPendingEvent(BaseEvent):
    """A payment row has been created and is awaiting the gateway.

    UNLIKE ITS THREE SIBLINGS, THIS IS NOT A TRANSITION. PENDING is the state a
    Payment is BORN in -- there is no mark_payment_pending, because nothing moves
    a payment into PENDING; create_payment constructs it that way. So the
    authoritative point is creation, and creation happens in exactly one place.

    Same two fields as PaymentSuccessEvent, and deliberately no wider. No amount:
    the patient is told a payment is awaiting confirmation and sent to the
    application, where the figure actually lives. WhatsApp is the least private
    channel the platform has.
    """

    event_type: Literal[
        "PAYMENT_PENDING"
    ]

    user_id: int
    appointment_id: int


class PaymentFailedEvent(BaseEvent):
    """A payment that was PENDING and is now FAILED.

    Shaped exactly like PaymentSuccessEvent, and deliberately no wider. The
    failure reason is NOT carried: it is gateway text stored in
    payment_metadata, it is unbounded, and every consumer of this event is a
    patient-facing notification channel. WhatsApp in particular is the least
    private channel the platform has, so an unbounded string from bKash is the
    last thing that should be able to reach it.

    No amount either, for the same reason PAYMENT_SUCCESS carries none: the
    patient is told the payment did not go through and directed to the
    authenticated application, where the details actually live.

    Published from mark_payment_failed, which fires on the PENDING -> FAILED
    transition only -- so a re-delivered webhook publishes nothing the second
    time.
    """

    event_type: Literal[
        "PAYMENT_FAILED"
    ]

    user_id: int
    appointment_id: int


class PaymentRefundedEvent(BaseEvent):

    event_type: Literal[
        "PAYMENT_REFUNDED"
    ]

    user_id: int
    appointment_id: int

    payment_id: int

    refund_transaction_id: str
    refunded_amount: str


class PrescriptionCreatedEvent(BaseEvent):

    event_type: Literal[
        "PRESCRIPTION_CREATED"
    ]

    prescription_id: int
    appointment_id: int
    patient_id: int
    doctor_id: int


class PrescriptionIssuedEvent(BaseEvent):

    event_type: Literal[
        "PRESCRIPTION_ISSUED"
    ]

    prescription_id: int
    appointment_id: int
    patient_id: int
    doctor_id: int
    issued_at: str




class PrescriptionUpdatedEvent(BaseEvent):

    event_type: Literal[
        "PRESCRIPTION_UPDATED"
    ]

    prescription_id: int
    appointment_id: int
    patient_id: int
    doctor_id: int


class PrescriptionRevisedEvent(BaseEvent):

    event_type: Literal[
        "PRESCRIPTION_REVISED"
    ]

    old_prescription_id: int
    new_prescription_id: int

    appointment_id: int

    patient_id: int
    doctor_id: int

    revision_number: int

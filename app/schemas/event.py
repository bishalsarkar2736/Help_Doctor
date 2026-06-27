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

    changed_by: int
    new_status: str


# =========================
# PAYMENT SUCCESS
# =========================
class PaymentSuccessEvent(BaseEvent):

    event_type: Literal[
        "PAYMENT_SUCCESS"
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


class ConsultationStartedEvent(BaseEvent):

    event_type: Literal[
        "CONSULTATION_STARTED"
    ]

    appointment_id: int
    patient_id: int
    doctor_id: int


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

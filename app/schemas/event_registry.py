from app.schemas.event import (
    AppointmentCreatedEvent,
    AppointmentConfirmedEvent,
    AppointmentCancelledEvent,
    AppointmentRescheduledEvent,
    AppointmentStatusChangedEvent,
    PaymentSuccessEvent,
    PrescriptionCreatedEvent,
    PrescriptionIssuedEvent,
    ConsultationStartedEvent,
    PrescriptionUpdatedEvent,
    PrescriptionRevisedEvent,
    PaymentRefundedEvent,
    PatientNextInQueueEvent,
    ConsultationCompletedEvent
)

EVENT_SCHEMAS = {
    "APPOINTMENT_CREATED":
        AppointmentCreatedEvent,

    "APPOINTMENT_CONFIRMED":
        AppointmentConfirmedEvent,

    "APPOINTMENT_CANCELLED":
        AppointmentCancelledEvent,

    "APPOINTMENT_RESCHEDULED":
        AppointmentRescheduledEvent,

    "APPOINTMENT_STATUS_CHANGED":
        AppointmentStatusChangedEvent,

    "PAYMENT_SUCCESS":
        PaymentSuccessEvent,
    
    "PRESCRIPTION_CREATED": 
        PrescriptionCreatedEvent,

    "PRESCRIPTION_ISSUED": 
        PrescriptionIssuedEvent,

    "CONSULTATION_STARTED": 
        ConsultationStartedEvent,

    "PATIENT_NEXT_IN_QUEUE": 
        PatientNextInQueueEvent,

    "CONSULTATION_COMPLETED":
        ConsultationCompletedEvent,

    "PRESCRIPTION_UPDATED": 
        PrescriptionUpdatedEvent,

    "PRESCRIPTION_REVISED": 
        PrescriptionRevisedEvent,
    
    "PAYMENT_REFUNDED" :
        PaymentRefundedEvent,

}
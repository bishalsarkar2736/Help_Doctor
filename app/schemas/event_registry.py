from app.schemas.event import (
    AppointmentCreatedEvent,
    AppointmentReminderEvent,
    AppointmentRescheduleRequestEvent,
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

    # Was missing in the other direction: the reminder job published an event on
    # every run and nothing here matched it, so the worker logged
    # "skipping_unsupported_event", marked it processed, and the reminder was
    # gone -- while the appointment had already been flagged reminder_sent.
    "APPOINTMENT_REMINDER":
        AppointmentReminderEvent,

    # Was missing. The event was published and the dispatcher had a handler for
    # it, but with no schema here the outbox worker logged
    # "skipping_unsupported_event", marked the row processed and returned -- so a
    # patient's reschedule request never reached the doctor, and left no failure
    # behind to notice.
    "APPOINTMENT_RESCHEDULE_REQUEST":
        AppointmentRescheduleRequestEvent,

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
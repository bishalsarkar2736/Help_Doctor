from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.appointment import AppointmentStatus


class AdminCancelledAppointmentItem(BaseModel):
    """One row of the cancelled-appointment audit.

    An allowlist, not the ORM row. The endpoint previously returned
    `Appointment` entities with no response model, so every column on the table
    was serialised — `notes`, `consultation_fee`, `time_range`, the queue
    timestamps — none of which answer the question this audit exists to ask:
    which appointment was cancelled, by whom, when, and why.

    Fields are added here deliberately rather than inherited, so a column added
    to the table later does not silently join the response.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    doctor_id: int
    patient_id: int
    clinic_id: int
    scheduled_at: datetime
    status: AppointmentStatus
    cancelled_by: int | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None

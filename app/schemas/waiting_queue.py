from datetime import datetime

from pydantic import BaseModel


class QueuePatient(BaseModel):
    appointment_id: int
    patient_id: int
    patient_name: str
    scheduled_at: datetime
    waiting_started_at: datetime | None


class WaitingQueueSummary(BaseModel):
    current_patient: QueuePatient | None
    waiting: list[QueuePatient]
    queue_length: int
    average_wait_minutes: int


class QueuePositionOut(BaseModel):
    appointment_id: int
    patient_name: str
    position: int | None
    estimated_wait_minutes: int

class QueueStatsOut(BaseModel):
    current_patient: QueuePatient | None
    next_patient: QueuePatient | None
    waiting_count: int
    average_wait_minutes: int
from pydantic import BaseModel


class DoctorQueueSummary(BaseModel):
    doctor_id: int
    doctor_name: str

    current_patient: str | None

    queue_length: int

    average_wait_minutes: int


class ReceptionQueueSummary(BaseModel):
    doctors: list[DoctorQueueSummary]
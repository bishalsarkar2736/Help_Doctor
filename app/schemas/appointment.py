from datetime import datetime
from pydantic import BaseModel


class AppointmentOut(BaseModel):
    id: int
    scheduled_at: datetime
    status: str
    notes: str | None

    doctor_name: str
    specialization: str

    class Config:
        from_attributes = True

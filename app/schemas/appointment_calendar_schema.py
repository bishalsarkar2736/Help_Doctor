from datetime import datetime

from pydantic import BaseModel


class CalendarAppointmentResponse(
    BaseModel
):
    id: int

    title: str

    doctor_id: int

    doctor_name: str

    start: datetime

    end: datetime

    status: str
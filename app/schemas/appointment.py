from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.models.appointment import AppointmentStatus
from app.schemas.doctor import DoctorPublic
from app.schemas.public_user import UserPublic


class AppointmentCreate(BaseModel):
    doctor_id: int
    scheduled_at: datetime   # ✅ THIS FIXES YOUR ERROR
    notes: str | None = None
    

class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scheduled_at: datetime
    status: str
    notes: str | None

    doctor_name: str
    specialization: str

    # class Config:
    #     from_attributes = True




class DoctorAppointmentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scheduled_at: datetime
    status: AppointmentStatus

    patient_name: str
    patient_email: str
    notes : str | None=None


    # class Config:
    #     from_attributes = True



class TimeSlotOut(BaseModel):
    starts_at: datetime
    ends_at: datetime


class AppointmentDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int

    doctor_id: int
    patient_id: int

    scheduled_at: datetime
    status: str

    notes: str | None = None

    cancel_reason: str | None = None

    cancelled_at: datetime | None = None
    confirmed_at: datetime | None = None
    completed_at: datetime | None = None

    reminder_sent: bool
    version: int

    created_at: datetime

    time_slot: TimeSlotOut | None = None

    doctor: DoctorPublic
    patient: UserPublic

    # class Config:
    #     from_attributes = Trues
from datetime import datetime

from pydantic import BaseModel


class DoctorDashboardAppointment(
    BaseModel,
):
    id: int
    patient_id: int
    patient_name: str
    scheduled_at: datetime
    status: str


class DoctorDashboardRecentPatient(
    BaseModel,
):
    patient_id: int
    patient_name: str
    last_visit: datetime


class DoctorDashboardResponse(
    BaseModel,
):
    today_appointments: int
    upcoming_appointments: int
    pending_appointments: int
    completed_today: int
    cancelled_today: int

    recent_appointments: list[
        DoctorDashboardAppointment
    ]

    today_schedule: list[
        DoctorDashboardAppointment
    ]

    recent_patients: list[
        DoctorDashboardRecentPatient
    ]
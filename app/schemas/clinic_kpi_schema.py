from pydantic import BaseModel


class ClinicKPIResponse(BaseModel):
    total_revenue: float
    total_patients: int
    total_appointments: int
    conversion_rate: float
    completion_rate: float

    patients_today: int
    patients_this_month: int

    appointments_today: int
    appointments_this_month: int

    average_revenue : float
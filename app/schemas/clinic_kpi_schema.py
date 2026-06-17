from pydantic import BaseModel


class ClinicKPIResponse(BaseModel):
    total_revenue: float
    total_patients: int
    total_appointments: int
    conversion_rate: float
    completion_rate: float


from pydantic import BaseModel


class DoctorRevenueItem(BaseModel):
    doctor_id: int
    doctor_name: str
    specialization: str

    revenue: float
    successful_payments: int


class DoctorRevenueDashboardResponse(BaseModel):
    total_revenue: float
    total_doctors: int

    doctors: list[DoctorRevenueItem]


class DoctorRevenueTrendItem(BaseModel):
    month: str
    revenue: float
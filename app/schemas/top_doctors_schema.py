from pydantic import BaseModel


class TopDoctorItem(BaseModel):
    doctor_id: int
    doctor_name: str
    specialization: str

    revenue: float
    successful_payments: int


class TopDoctorsResponse(BaseModel):
    doctors: list[TopDoctorItem]
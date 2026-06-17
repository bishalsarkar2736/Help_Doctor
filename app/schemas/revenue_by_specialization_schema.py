from pydantic import BaseModel


class RevenueBySpecializationResponse(
    BaseModel
):
    specialization: str
    revenue: float
    payments: int
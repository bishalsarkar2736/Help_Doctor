from pydantic import BaseModel


class AppointmentStatusItem(
    BaseModel
):
    status: str
    count: int


class AppointmentStatusDistributionResponse(
    BaseModel
):
    items: list[
        AppointmentStatusItem
    ]
from datetime import time
from pydantic import BaseModel, Field,ConfigDict


class AvailabilityBase(BaseModel):
    day_of_week: int = Field(ge=0, le=6)
    start_time: time
    end_time: time


class AvailabilityCreate(AvailabilityBase):
    pass


class AvailabilityUpdate(BaseModel):
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    start_time: time | None = None
    end_time: time | None = None
    is_available: bool | None = None


class AvailabilityOut(AvailabilityBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_available: bool

    # class Config:
    #     from_attributes = True

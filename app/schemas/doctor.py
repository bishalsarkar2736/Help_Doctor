from pydantic import BaseModel,ConfigDict,Field
from datetime import datetime



class DoctorListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    specialization: str
    experience_years: int
    bio: str | None

    # class Config:
    #     from_attributes = True



class DoctorPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int

    specialization: str
    experience_years: int
    bio: str | None = None

    is_verified: bool
    created_at: datetime

    # class Config:
    #     from_attributes = True


class DoctorProfileUpdate(BaseModel):
    qualification: str | None = Field(
        default=None,
        max_length=200,
    )

    medical_registration_number: str | None = Field(
        default=None,
        max_length=100,
    )
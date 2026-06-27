from pydantic import BaseModel,ConfigDict,Field
from datetime import datetime
from decimal import Decimal


class DoctorListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    specialization: str
    experience_years: int
    bio: str | None

    consultation_fee: Decimal

    

class DoctorPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int

    specialization: str
    experience_years: int
    bio: str | None = None

    consultation_fee: Decimal

    is_verified: bool
    created_at: datetime

    

class DoctorProfileUpdate(BaseModel):
    qualification: str | None = Field(
        default=None,
        max_length=200,
    )

    medical_registration_number: str | None = Field(
        default=None,
        max_length=100,
    )

    consultation_fee: Decimal | None = Field(
        default=None,
        ge=0,
    )
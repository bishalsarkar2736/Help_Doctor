from pydantic import BaseModel,ConfigDict,Field
from datetime import datetime
from decimal import Decimal

from app.models.doctor import DoctorStatus



class DoctorProfileCreate(BaseModel):
    specialization: str = Field(
        ...,
        max_length=100,
    )

    experience_years: int = Field(
        ...,
        ge=0,
    )

    bio: str | None = Field(
        default=None,
        max_length=500,
    )


class DoctorProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int

    specialization: str
    experience_years: int
    bio: str | None

    status: DoctorStatus
    created_at: datetime


class DoctorListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    specialization: str
    experience_years: int
    bio: str | None

    consultation_fee: Decimal

    clinic_id: int | None = None
    clinic_name: str | None = None


class DoctorDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    specialization: str
    experience_years: int
    bio: str | None
    qualification: str | None = None
    consultation_fee: Decimal
    clinic_id: int | None = None
    clinic_name: str | None = None


class DoctorMe(BaseModel):
    """The doctor's OWN profile — returned regardless of approval status.

    Unlike DoctorDetail (public, approved-only), this lets a PENDING /
    REJECTED / SUSPENDED doctor read their own record so the workspace can
    render the correct onboarding / status gate.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int

    specialization: str
    experience_years: int
    bio: str | None = None
    qualification: str | None = None
    medical_registration_number: str | None = None

    consultation_fee: Decimal

    status: DoctorStatus
    rejection_reason: str | None = None

    clinic_id: int | None = None
    clinic_name: str | None = None

    signature_file_path: str | None = None
    signature_uploaded_at: datetime | None = None

    created_at: datetime


class DoctorPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int

    specialization: str
    experience_years: int
    bio: str | None = None

    consultation_fee: Decimal

    status: DoctorStatus
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
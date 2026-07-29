from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.doctor import DoctorStatus


class AdminDoctorListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    specialization: str
    experience_years: int
    bio: str | None
    status: DoctorStatus
    is_active: bool

    # Audit
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None


class DoctorRejectRequest(BaseModel):
    reason: str | None = None

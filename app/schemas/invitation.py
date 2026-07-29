from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, ConfigDict

from app.models.user import UserRole
from app.models.invitation import InvitationStatus
from app.security.password_policy import StrongPassword


class InvitationCreate(BaseModel):
    email: EmailStr
    role: UserRole
    clinic_id: int


class InvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: UserRole
    clinic_id: int
    status: InvitationStatus
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime


class InvitationPreview(BaseModel):
    """Public, safe-to-show details for the accept-invite page."""

    email: EmailStr
    role: UserRole
    clinic_id: int
    clinic_name: str
    expires_at: datetime


class InvitationAccept(BaseModel):
    token: str
    full_name: str = Field(min_length=1, max_length=255)
    password: StrongPassword


class InvitationAcceptResponse(BaseModel):
    message: str
    user_id: int
    email: EmailStr
    role: UserRole

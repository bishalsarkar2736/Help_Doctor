from datetime import datetime
from pydantic import BaseModel, EmailStr,ConfigDict

from app.models.user import UserRole


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str | None = None

    role: UserRole
    created_at: datetime

    # class Config:
    #     from_attributes = True
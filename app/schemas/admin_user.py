from pydantic import BaseModel,ConfigDict
from app.models.user import UserRole

class AdminUserItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str | None = None
    role: UserRole
    is_active: bool
    clinic_id: int | None = None

    # class Config:
    #     from_attributes = True
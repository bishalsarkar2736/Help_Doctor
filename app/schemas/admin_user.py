from pydantic import BaseModel,ConfigDict
from app.models.user import UserRole

class AdminUserItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: UserRole
    is_active: bool

    # class Config:
    #     from_attributes = True
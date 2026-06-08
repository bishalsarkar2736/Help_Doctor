from pydantic import BaseModel,ConfigDict

class AdminDoctorListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    specialization: str
    experience_years: int
    bio: str | None
    is_verified: bool
    is_active: bool

    # class Config:
    #     from_attributes = True
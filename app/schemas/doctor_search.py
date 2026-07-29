from pydantic import BaseModel,ConfigDict


class DoctorSearchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: str
    specialization: str


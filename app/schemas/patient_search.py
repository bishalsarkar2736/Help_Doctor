from pydantic import BaseModel, EmailStr,ConfigDict


class PatientSearchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int          # Patient record id
    user_id: int     # User id — used as patient_id when booking on their behalf
    full_name: str
    email: EmailStr
    phone: str | None = None

from pydantic import BaseModel

class PatientBase(BaseModel):
    phone:str
    address:str
    date_of_birth:str
    gender:str


class PatientCreate(PatientBase):
    pass

class PatientRead(PatientBase):
    id:int
    user_id:int

    class Config:
        from_attributes = True
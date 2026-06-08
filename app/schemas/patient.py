from pydantic import BaseModel,ConfigDict

class PatientBase(BaseModel):

    phone:str
    address:str
    date_of_birth:str
    gender:str


class PatientCreate(PatientBase):
    pass

class PatientRead(PatientBase):
    model_config = ConfigDict(from_attributes=True)

    id:int
    user_id:int

    # class Config:
    #     from_attributes = True
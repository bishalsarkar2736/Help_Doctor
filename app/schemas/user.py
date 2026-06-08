from pydantic import BaseModel, EmailStr, Field,ConfigDict
from typing import Optional

from datetime import datetime
from app.models.user import UserRole



#Base Schema
class UserBase(BaseModel):
    email : EmailStr
    full_name : str
    role: UserRole = UserRole.RECEPTIONIST
    is_active:bool = True


# create User (register)

class UserCreate(UserBase):
    password : str = Field(
        min_length= 8,
        max_length=72,
        description="User password (min 8 character)"
    )

# Login Schema

class UserLogin(BaseModel):
    email : EmailStr
    password : str


# Read User
class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id : int
    created_at : datetime
    updated_at : datetime
   

    # class Config:
    #     from_attributes = True

#Token Schemas

class Token(BaseModel):
    access_token:str
    refresh_token: str
    token_type : str = 'bearer'

class TokenPayload(BaseModel):
    sub:int
    role:UserRole
    exp:int
    
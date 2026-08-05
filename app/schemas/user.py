from pydantic import BaseModel, EmailStr, Field,ConfigDict, field_validator
from typing import Optional

from datetime import datetime
from app.models.user import UserRole
from app.security.password_policy import StrongPassword



#Base Schema
class UserBase(BaseModel):
    email : EmailStr
    full_name : str = Field(max_length=255)
    role: UserRole = UserRole.RECEPTIONIST
    is_active:bool = True


# create User (register)

# Patients are the ONLY public users. Everything else is provisioned:
#   DOCTOR / RECEPTIONIST -> invited by a clinic admin
#   ADMIN                 -> invited by the super admin
#   SUPER_ADMIN           -> seeded by scripts/create_super_admin.py only
# A clinic decides who practises under its name, so a doctor cannot self-attach.
SELF_REGISTERABLE_ROLES = {UserRole.PATIENT}


class UserCreate(UserBase):
    # Which version of each legal document the user was shown and accepted.
    # Required: an account cannot be created without a consent record, because
    # the record is the evidence and retrofitting it later is guesswork.
    # The server rejects anything but the currently published version.
    accepted_terms_version: str = Field(
        description="Version of the Terms of Service shown to the user",
    )
    accepted_privacy_version: str = Field(
        description="Version of the Privacy Policy shown to the user",
    )

    # Patient is the safe default; explicitly NOT inherited from UserBase,
    # whose RECEPTIONIST default is wrong for public signup.
    role: UserRole = UserRole.PATIENT

    password: StrongPassword = Field(
        description="Min 8 chars, at least one letter and one number",
    )

    # Scoped to UserCreate (registration input) only — not UserBase/UserRead —
    # so reading back pre-existing users never re-validates and fails on
    # names written before this rule existed.
    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Full name cannot be empty.")
        return v

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: UserRole) -> UserRole:
        # Without this, anyone could POST /auth/register with
        # role="super_admin" and mint themselves a platform account.
        if v not in SELF_REGISTERABLE_ROLES:
            raise ValueError(
                "This account type cannot be created by signing up. "
                "Staff accounts are created by invitation."
            )
        return v

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

    # No longer returned to browsers: the refresh token is delivered as an
    # httpOnly cookie so JavaScript cannot read it. Left on the model (as None)
    # rather than removed, because the service layer still builds it and
    # non-browser callers may still be issued one.
    refresh_token: str | None = None
    token_type : str = 'bearer'

    # This account's role mandates a second factor and it has not been set up
    # yet. The token is still issued — enrolling requires an authenticated
    # session, so refusing would lock the account out permanently — and the
    # client uses this to route straight to enrolment. Defaults to False so
    # every other issuance path (refresh, google) is unaffected.
    mfa_enrollment_required: bool = False

class TokenPayload(BaseModel):
    sub:int
    role:UserRole
    exp:int
    
from pydantic import BaseModel,Field,EmailStr

from app.security.password_policy import StrongPassword



class LoginJSONRequest(BaseModel):
    email: EmailStr
    password: str
    mfa_code: str | None = None


class MfaCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=10)


class VerifyEmailOtpRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=10)


class LogoutRequest(BaseModel):
    refresh_token: str


class GoogleLoginRequest(BaseModel):
    token: str



class RefreshTokenRequest(BaseModel):
    refresh_token: str



class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=8)
    new_password: StrongPassword


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: StrongPassword

class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr
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
    # Optional: the refresh token normally arrives in an httpOnly cookie. Kept
    # so a session issued before the cookie migration can still be logged out,
    # and so non-browser clients keep working.
    refresh_token: str | None = None


class GoogleLoginRequest(BaseModel):
    token: str



class RefreshTokenRequest(BaseModel):
    # Optional for the same reason as LogoutRequest — see app/security/auth_cookies.py.
    refresh_token: str | None = None



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
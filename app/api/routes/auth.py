from fastapi import APIRouter, Depends, status, HTTPException, Request, Form
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.security import OAuth2PasswordRequestForm
from app.security.jwt import get_current_user
from app.models.user import User
from app.schemas.auth import ChangePasswordRequest
from app.services.auth_service import change_password
from app.db.postgres import get_db
from app.schemas.user import UserCreate, UserRead, Token
from app.services.auth_service import (
    register_user,
    authentication_user,
    authenticate_google_user,
    refresh_tokens,
    logout_user,
    forgot_password,
    reset_password,
    send_verification_email,
    resend_verification_email,
    verify_email as verify_email_service,
    verify_email_otp,
)
from app.schemas.auth import (
    RefreshTokenRequest,
    GoogleLoginRequest,
    LogoutRequest,
    LoginJSONRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    VerifyEmailRequest,
    ResendVerificationRequest,
    MfaCodeRequest,
    VerifyEmailOtpRequest,
)
from app.try_except.exceptions import BadRequestError
from app.security.mfa import (
    generate_secret,
    provisioning_uri,
    verify_code,
    qr_data_uri,
)
from app.core.limiter import limiter



router = APIRouter(prefix="/auth", tags=["Authentication"])



# ---------------- REGISTER ----------------

@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("5/minute")
async def register(
    request: Request,
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db),
):
    return await register_user(db, user_in)


# ---------------- LOGIN (FORM) ----------------

@router.post("/login", response_model=Token)
@limiter.limit("5/minute")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    mfa_code: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    token = await authentication_user(
        db=db,
        email=form_data.username,
        password=form_data.password,
        mfa_code=mfa_code,
    )

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    return token


# ---------------- LOGIN (JSON) ----------------

@router.post("/login-json", response_model=Token)
@limiter.limit("5/minute")
async def login_json(
    request: Request,
    body: LoginJSONRequest,
    db: AsyncSession = Depends(get_db),
):
    token = await authentication_user(
        db=db,
        email=body.email,
        password=body.password,
        mfa_code=body.mfa_code,
    )

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    return token


@router.post("/google", response_model=Token)
@limiter.limit("10/minute")
async def google_login(
    request: Request,
    body: GoogleLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    return await authenticate_google_user(
        db=db,
        token=body.token,
    )


@router.post("/change-password")
async def change_password_endpoint(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await change_password(
        db=db,
        user=current_user,
        current_password=body.current_password,
        new_password=body.new_password,
    )


@router.post("/forgot-password")
@limiter.limit("5/minute")
async def forgot_password_endpoint(
    request: Request,
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    return await forgot_password(
        db=db,
        email=body.email,
    )


@router.post("/reset-password")
@limiter.limit("5/minute")
async def reset_password_endpoint(
    request: Request,
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    return await reset_password(
        db=db,
        token=body.token,
        new_password=body.new_password,
    )

@router.post("/send-verification")
async def send_verification_endpoint(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await send_verification_email(
        db=db,
        user=user,
    )


@router.post("/verify-email")
async def verify_email_endpoint(
    request: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    return await verify_email_service(
        db=db,
        token=request.token,
    )


@router.post("/verify-otp")
# Tight limit: a 6-digit code is brute-forceable, so throttle by IP on top of
# the per-code attempt cap enforced in the service.
@limiter.limit("10/minute")
async def verify_email_otp_endpoint(
    request: Request,
    body: VerifyEmailOtpRequest,
    db: AsyncSession = Depends(get_db),
):
    return await verify_email_otp(
        db=db,
        email=body.email,
        code=body.code,
    )


@router.post("/resend-verification")
@limiter.limit("5/minute")
async def resend_verification_endpoint(
    request: Request,
    body: ResendVerificationRequest,
    db: AsyncSession = Depends(get_db),
):
    return await resend_verification_email(
        db=db,
        email=body.email,
    )

# ---------------- REFRESH TOKEN ----------------

@router.post("/refresh", response_model=Token)
@limiter.limit("10/minute")
async def refresh_token_endpoint(
    request: Request,
    body: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    return await refresh_tokens(db, body.refresh_token)


# ---------------- LOGOUT ----------------

@router.post("/logout")
async def logout(
    body: LogoutRequest,
    db: AsyncSession = Depends(get_db),
):
    return await logout_user(db, body.refresh_token)


# ---------------- MFA (TOTP) ----------------

@router.post("/mfa/setup")
async def mfa_setup(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.mfa_enabled:
        raise BadRequestError("MFA is already enabled")

    secret = generate_secret()
    current_user.mfa_secret = secret  # pending until verified by /mfa/enable
    await db.flush()

    uri = provisioning_uri(secret, current_user.email)
    return {
        "secret": secret,
        "otpauth_uri": uri,
        "qr_data_uri": qr_data_uri(uri),
    }


@router.post("/mfa/enable")
@limiter.limit("10/minute")
async def mfa_enable(
    request: Request,
    body: MfaCodeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.mfa_enabled:
        raise BadRequestError("MFA is already enabled")
    if not current_user.mfa_secret:
        raise BadRequestError("Start MFA setup first")
    if not verify_code(current_user.mfa_secret, body.code):
        raise BadRequestError("Invalid code")

    current_user.mfa_enabled = True
    await db.flush()
    return {"mfa_enabled": True}


@router.post("/mfa/disable")
@limiter.limit("10/minute")
async def mfa_disable(
    request: Request,
    body: MfaCodeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.mfa_enabled:
        raise BadRequestError("MFA is not enabled")
    if not verify_code(current_user.mfa_secret, body.code):
        raise BadRequestError("Invalid code")

    current_user.mfa_enabled = False
    current_user.mfa_secret = None
    await db.flush()
    return {"mfa_enabled": False}







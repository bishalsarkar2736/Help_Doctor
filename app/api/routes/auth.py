from fastapi import APIRouter, Depends, status, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.security import OAuth2PasswordRequestForm

from app.db.postgres import get_db
from app.schemas.user import UserCreate, UserRead, Token
from app.services.auth_service import (
    register_user,
    authentication_user,
    get_or_create_google_user,
    refresh_tokens,
    logout_user,
)
from app.security.jwt import create_access_token
from app.schemas.auth import RefreshTokenRequest
from app.core.limiter import limiter

from pydantic import BaseModel, EmailStr


router = APIRouter(prefix="/auth", tags=["Authentication"])


# ---------------- REQUEST MODELS ----------------

class LoginJSONRequest(BaseModel):
    email: EmailStr
    password: str


class LogoutRequest(BaseModel):
    refresh_token: str


class GoogleLoginRequest(BaseModel):
    token: str


# ---------------- REGISTER ----------------

@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
async def register(
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
    db: AsyncSession = Depends(get_db),
):
    token = await authentication_user(
        db=db,
        email=form_data.username,
        password=form_data.password,
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
    )

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    return token


# ---------------- LOGOUT ----------------

@router.post("/logout")
async def logout(
    body: LogoutRequest,
    db: AsyncSession = Depends(get_db),
):
    return await logout_user(db, body.refresh_token)


# ---------------- GOOGLE LOGIN ----------------

@router.post("/google", response_model=Token)
async def google_login(
    body: GoogleLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    user = await get_or_create_google_user(db, body.token)

    access_token = create_access_token(
        data={
            "sub": str(user.id),   # 🔥 IMPORTANT FIX
            "role": user.role,
        }
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }


# ---------------- REFRESH TOKEN ----------------

@router.post("/refresh", response_model=Token)
async def refresh_token_endpoint(
    body: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    return await refresh_tokens(db, body.refresh_token)
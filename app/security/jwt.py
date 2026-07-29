from datetime import datetime, timedelta
from typing import Optional

from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, WebSocket
from fastapi.security import OAuth2PasswordBearer
from app.db.postgres import AsyncSessionLocal
from app.config import get_settings
from app.models.user import User
from app.core.time import UTC
from app.db.postgres import get_db
from app.try_except.context import user_id_ctx, clinic_id_ctx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload



settings = get_settings()


# =========================
# PASSWORD CONFIG
# =========================
pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto"
)

oauth2_schema = OAuth2PasswordBearer(tokenUrl="auth/login")


# =========================
# PASSWORD HANDLING
# =========================
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# =========================
# ACCESS TOKEN (JWT)
# =========================
def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    to_encode = data.copy()

    expire = datetime.now(UTC) + (
        expires_delta
        if expires_delta
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    to_encode.update({
        "exp": expire,
        "type": "access",   # important for validation
    })

    return jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.ALGORITHM],  # FIXED (must be list)
        )

        # Validate token type
        if payload.get("type") != "access":
            return None

        return payload

    except JWTError:
        return None


# =========================
# FASTAPI DEPENDENCY
# =========================
# def get_current_user(token: str = Depends(oauth2_schema)):
#     payload = decode_access_token(token)

#     if payload is None:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Invalid or expired token",
#         )

#     return payload

# async def get_current_user(
#     token: str = Depends(oauth2_schema),
# ) -> User:
#     payload = decode_access_token(token)

#     if payload is None:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Invalid or expired token",
#         )

#     user_id = payload.get("sub")
#     if not user_id:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Invalid token payload",
#         )

#     async with AsyncSessionLocal() as db:
#         user = await db.get(User, int(user_id))

#         if not user:
#             raise HTTPException(
#                 status_code=status.HTTP_401_UNAUTHORIZED,
#                 detail="User not found",
#             )

#         if not user.is_active:
#             raise HTTPException(
#                 status_code=status.HTTP_403_FORBIDDEN,
#                 detail="Inactive user",
#             )
        
#         print("JWT PAYLOAD:", payload)
#         print("USER FROM DB:", user.id, user.role)

#         return user


async def get_current_user(
    token: str = Depends(oauth2_schema),
    db: AsyncSession = Depends(get_db),
) -> User:

    payload = decode_access_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    user = await db.get(User, int(user_id))

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )

    # Make user/clinic available to structured logging for this request.
    user_id_ctx.set(user.id)
    clinic_id_ctx.set(user.clinic_id)

    return user

# =========================
# WEBSOCKET TOKEN DECODE
# =========================
async def decode_token_from_ws(websocket: WebSocket) -> User | None:
    """
    Production-ready WebSocket authentication

    Priority:
    1. Authorization header (Bearer)
    2. Query param fallback (?token=)
    """

    # 🔹 1. Try header first (production standard)
    token = websocket.headers.get("authorization")

    if token and token.startswith("Bearer "):
        token = token.replace("Bearer ", "")

    # 🔹 2. Fallback to query param (browser support)
    if not token:
        token = websocket.query_params.get("token")

    # No token → reject cleanly
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )

        # 🔒 Validate token type
        if payload.get("type") != "access":
            raise JWTError

        user_id = payload.get("sub")
        if not user_id:
            raise JWTError

    except JWTError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None

    # 🔹 Fetch user (DB validation)
    async with AsyncSessionLocal() as db:

        result = await db.execute(
            select(User)
            .options(
                selectinload(User.doctor),
            )
            .where(User.id == int(user_id))
        )

        user = result.scalar_one_or_none()

        #user = await db.get(User, int(user_id))

        if not user:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return None

        return user
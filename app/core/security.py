from datetime import datetime, timedelta
from jose import jwt, JWTError
from secrets import token_urlsafe
from app.config import get_settings
from fastapi import HTTPException, status
from app.core.time import UTC

settings = get_settings()

# def create_access_token(data:dict) -> str:
#     to_encode = data.copy()
#     expire = datetime.now(UTC) + timedelta(
#         minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
#     )
#     to_encode.update({"exp":expire, "type":"access"})

#     return jwt.encode(
#         to_encode,
#         settings.JWT_SECRET_KEY,
#         algorithm=settings.ALGORITHM
#     )

# def create_refresh_token() ->str:
#     #opaque token (stored in DB)
#     return token_urlsafe(64)


# def decode_token(token:str) -> dict:
#     try:
#         payload = jwt.decode(
#             token,
#             settings.JWT_SECRET_KEY,
#             algorithms=[settings.ALGORITHM]
#         )
#         return payload
#     except JWTError:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Invalid token"
#         )



# ==============================
# ACCESS TOKEN (JWT - Stateless)
# ==============================
# def create_access_token(data: dict) -> str:
#     to_encode = data.copy()

#     expire = datetime.now(UTC) + timedelta(
#         minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
#     )

#     to_encode.update({
#         "exp": expire,
#         "type": "access",
#     })

#     return jwt.encode(
#         to_encode,
#         settings.JWT_SECRET_KEY,
#         algorithm=settings.ALGORITHM,
#     )


# # =====================================
# # REFRESH TOKEN (Opaque - Stored in DB)
# # =====================================
# def create_refresh_token() -> str:
#     # Secure random token (NOT JWT)
#     return token_urlsafe(64)


# # ====================
# # ACCESS TOKEN DECODE
# # ====================
# def decode_token(token: str) -> dict:
#     try:
#         payload = jwt.decode(
#             token,
#             settings.JWT_SECRET_KEY,
#             algorithms=[settings.ALGORITHM],
#         )

#         if payload.get("type") != "access":
#             raise HTTPException(
#                 status_code=status.HTTP_401_UNAUTHORIZED,
#                 detail="Invalid token type",
#             )

#         return payload

#     except JWTError:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Invalid or expired token",
#         )


"""
Temporary bridge file.

All JWT logic now lives in:
    app.security.jwt

This file re-exports functions to prevent import breakage.
"""

from app.security.jwt import (
    create_access_token,
    decode_access_token as decode_token,
)

from secrets import token_urlsafe


# =====================================
# REFRESH TOKEN (Opaque - Stored in DB)
# =====================================
def create_refresh_token() -> str:
    return token_urlsafe(64)
from datetime import datetime, timedelta
from jose import jwt, JWTError
from secrets import token_urlsafe
from app.config import get_settings
from fastapi import HTTPException, status


settings = get_settings()

def create_access_token(data:dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    to_encode.update({"exp":expire, "type":"access"})

    return jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.ALGORITHM
    )

def create_refresh_token() ->str:
    #opaque token (stored in DB)
    return token_urlsafe(64)


def decode_token(token:str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
 
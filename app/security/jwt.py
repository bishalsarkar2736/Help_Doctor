from datetime import datetime, timedelta
from typing import Optional

from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends,HTTPException,status,WebSocket
from fastapi.security import OAuth2PasswordBearer

from app.config import get_settings
from app.models.user import User
from app.db.postgres import AsyncSessionLocal



settings = get_settings()

pwd_context = CryptContext(
    schemes = ["bcrypt"],
    deprecated = "auto"
)

oauth2_schema = OAuth2PasswordBearer(tokenUrl="api/auth/login")


#passwrod handling

def hash_password(password:str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password : str, hashed_password:str) ->bool:
    return pwd_context.verify(plain_password,hashed_password)


#JWT handling

def create_access_token(data:dict,expires_delta:Optional[timedelta] = None):
    to_encode = data.copy()

    expire = datetime.utcnow() + (
        expires_delta
        if expires_delta
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    to_encode.update({'exp':expire})

    return jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.ALGORITHM
    )

def decode_access_token(token:str):
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=settings.ALGORITHM
        )
        return payload
    except JWTError:
        return None
    

# Dependency

def get_current_user(token: str = Depends(oauth2_schema)):
    payload = decode_access_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )
    return payload



async def decode_token_from_ws(websocket: WebSocket) -> User:
    token = websocket.headers.get("authorization")

    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise HTTPException(401, "Missing token")

    if token.startswith("Bearer "):
        token = token.replace("Bearer ", "")

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        user_id = payload.get("sub")
        if not user_id:
            raise JWTError
    except JWTError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise HTTPException(401, "Invalid token")

    async with AsyncSessionLocal() as db:
        user = await db.get(User, int(user_id))
        if not user:
            raise HTTPException(401, "User not found")

        return user

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select


from app.models.user import User,AuthProvider,UserRole
from app.schemas.user import UserCreate
from app.security.jwt import hash_password,verify_password,create_access_token
from app.security.google_oauth import verify_google_token
from app.config import get_settings

from datetime import datetime, timedelta
from app.core.time import UTC
from app.models.refresh_token import RefreshToken
from app.security.jwt import create_access_token
from app.core.security import create_refresh_token,decode_token
from app.try_except.exceptions import BadRequestError,UnauthorizedError,ForbiddenError

settings = get_settings()


# Register user
async def register_user(
        db : AsyncSession,
        user_in : UserCreate,
) -> User:
    result = await db.execute(
        select(User).where(User.email == user_in.email)
    )

    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise BadRequestError("Email aleady registerd")
    
    user = User(
        email = user_in.email,
        full_name = user_in.full_name,
        hashed_password = hash_password(user_in.password),
        role = user_in.role,
        is_active = True,
    )

    db.add(user)
    await db.flush()
    await db.refresh(user)

    return user

async def get_or_create_google_user(
        db : AsyncSession,
        token : str
) -> User:
    data = verify_google_token(token)

    stmt = select(User).where(User.email==data["email"])
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user:
        return user
    
    user = User(
        email = data["email"],
        full_name = data["full_name"],
        foogle_id = data["google_id"],
        auth_provider = AuthProvider.GOOGLE,
        role = UserRole.PATIENT,
        is_active = True,
    )

    db.add(user)
    await db.flush()
    await db.refresh(user)

    return user


# Authentication User

async def authentication_user(
    db: AsyncSession,
    email: str,
    password: str,
):
    result = await db.execute(
        select(User).where(User.email == email)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        raise UnauthorizedError("Invalid email or password")

    if not user.is_active:
        raise ForbiddenError("Inactive user")

    access_token = create_access_token(
        {
            "sub": user.id,
            "role": user.role.value,
        }
    )

    refresh_token = create_refresh_token(
        {
            "sub": user.id,
            "role": user.role.value,
        }
    )

    refresh = RefreshToken(
        token=refresh_token,
        user_id=user.id,
        expires_at=datetime.now(UTC)
        + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )

    db.add(refresh)
    await db.flush()


    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }



async def refresh_tokens(
    db: AsyncSession,
    refresh_token: str,
):
    payload = decode_token(refresh_token)

    if payload.get("type") != "refresh":
        raise UnauthorizedError("Invalid token type")

    user_id = payload.get("sub")
    role = payload.get("role")

    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token == refresh_token,
            RefreshToken.revoked.is_(False),
            RefreshToken.expires_at > datetime.now(UTC),
        )
    )
    db_token = result.scalar_one_or_none()

    if not db_token:
        raise UnauthorizedError("Refresh token revoked or expired")

    #  Rotate token
    db_token.revoked = True

    new_refresh_token = create_refresh_token(
        {"sub": user_id, "role": role}
    )

    new_db_token = RefreshToken(
        token=new_refresh_token,
        user_id=user_id,
        expires_at=datetime.now(UTC)
        + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )

    access_token = create_access_token(
        {"sub": user_id, "role": role}
    )

    db.add(new_db_token)
    await db.flush()


    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
    }

async def logout_user(
    db: AsyncSession,
    refresh_token: str,
):
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token == refresh_token,
            RefreshToken.revoked.is_(False),
        )
    )

    db_token = result.scalar_one_or_none()

    if not db_token:
        # already revoked or invalid → still treat as success
        return {"message": "Logged out"}

    db_token.revoked = True
    await db.flush()

    return {"message": "Logged out successfully"}


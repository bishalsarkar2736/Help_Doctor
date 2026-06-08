from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select


from app.models.user import User,AuthProvider,UserRole
from app.schemas.user import UserCreate
from app.security.jwt import hash_password,verify_password
from app.security.google_oauth import verify_google_token
from app.config import get_settings

from datetime import datetime, timedelta
from app.core.time import UTC
from app.models.refresh_token import RefreshToken
from app.security.jwt import create_access_token
from app.core.security import create_refresh_token
from app.try_except.exceptions import BadRequestError,UnauthorizedError,ForbiddenError
from app.try_except.audit import log_audit_event



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
    #await db.commit()
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
        google_id = data["google_id"],
        auth_provider = AuthProvider.GOOGLE,
        role = UserRole.PATIENT,
        is_active = True,
    )

    db.add(user)
    await db.flush()
    #await db.commit()
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
        {"sub": str(user.id), "role": user.role.value}
    )

    refresh_token = create_refresh_token()

    refresh = RefreshToken(
        token=refresh_token,
        user_id=user.id,
        expires_at=datetime.now(UTC)
        + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )

    db.add(refresh)
    await db.flush()
    #await db.commit()


    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


async def refresh_tokens(
    db: AsyncSession,
    refresh_token: str,
):
    # 1️⃣ Validate refresh token from DB
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token == refresh_token,
            RefreshToken.revoked.is_(False),
            RefreshToken.expires_at > datetime.now(UTC),
        )
    )
    db_token = result.scalar_one_or_none()

    if not db_token:
        raise UnauthorizedError("Invalid or expired refresh token")

    # 2️⃣ Fetch user
    user = await db.get(User, db_token.user_id)
    if not user:
        raise UnauthorizedError("User not found")

    # 3️⃣ Revoke old refresh token (rotation)
    db_token.revoked = True

    # 4️⃣ Create new refresh token (opaque)
    new_refresh_token = create_refresh_token()

    new_db_token = RefreshToken(
        token=new_refresh_token,
        user_id=user.id,
        expires_at=datetime.now(UTC)
        + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )

    db.add(new_db_token)

    # 5️⃣ Create new access token (JWT)
    access_token = create_access_token(
        {"sub": str(user.id), "role": user.role.value}
    )

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
    db_token.revoked_at = datetime.now(UTC)

    await log_audit_event(
        db=db,
        event_type="authentication",
        user_id=db_token.user_id,
        action="logout",
        resource="user_account",
        status="success",
    )

    #await db.commit()
    await db.flush()

    return {"message": "Logged out successfully"}





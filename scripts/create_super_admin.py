"""Bootstrap the platform Super Admin.

Super Admins are never self-registered. This script creates (or promotes)
the single platform Super Admin from configuration.

Usage:
    # Provide credentials via environment / .env:
    #   SUPER_ADMIN_EMAIL=owner@platform.com
    #   SUPER_ADMIN_PASSWORD=change-me-strong
    #   SUPER_ADMIN_NAME="Platform Owner"
    python -m scripts.create_super_admin

Idempotent: running it again promotes the existing account and (optionally)
resets its password if SUPER_ADMIN_PASSWORD is set.
"""

import asyncio

from sqlalchemy import select

from app.config import get_settings
from app.db.postgres import AsyncSessionLocal
from app.models.user import User, UserRole, AuthProvider
from app.security.jwt import hash_password


async def create_super_admin() -> None:
    settings = get_settings()

    email = settings.SUPER_ADMIN_EMAIL
    password = settings.SUPER_ADMIN_PASSWORD

    if not email or not password:
        raise SystemExit(
            "SUPER_ADMIN_EMAIL and SUPER_ADMIN_PASSWORD must be set "
            "(via environment or .env) to bootstrap the super admin."
        )

    async with AsyncSessionLocal() as db:
        existing = await db.scalar(
            select(User).where(User.email == str(email))
        )

        if existing is not None:
            existing.role = UserRole.SUPER_ADMIN
            existing.is_active = True
            existing.is_email_verified = True
            existing.hashed_password = hash_password(password)
            await db.commit()
            print(f"✅ Promoted existing user to SUPER_ADMIN: {email}")
            return

        user = User(
            email=str(email),
            full_name=settings.SUPER_ADMIN_NAME,
            hashed_password=hash_password(password),
            role=UserRole.SUPER_ADMIN,
            is_active=True,
            is_email_verified=True,
            auth_provider=AuthProvider.LOCAL,
        )
        db.add(user)
        await db.commit()
        print(f"✅ Created SUPER_ADMIN: {email}")


if __name__ == "__main__":
    asyncio.run(create_super_admin())

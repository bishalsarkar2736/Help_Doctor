"""Soft deletion of user accounts.

Users are never hard-deleted. Their appointments, prescriptions and payments
carry medical and financial retention obligations that outlive the account, and
since migration f3b6d81c2a05 the foreign keys to `users` are RESTRICT — the
database will refuse a hard delete rather than quietly cascade it away.

Deleting therefore means:
  * stamp `deleted_at`               (the tombstone)
  * clear `is_active`                (so every existing is_active check holds)
  * revoke every refresh token       (kill sessions that already exist)

Access tokens already issued stay valid until they expire (default 60 min);
`get_current_user` rejects the account on the next request because
`is_active` is false.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole
from app.try_except.exceptions import (
    BadRequestError,
    ForbiddenError,
    NotFoundError,
)

logger = logging.getLogger(__name__)


async def soft_delete_user(
    *,
    db: AsyncSession,
    actor: User,
    user_id: int,
) -> User:
    user = await db.scalar(select(User).where(User.id == user_id))

    if user is None:
        raise NotFoundError("User not found")

    if user.deleted_at is not None:
        raise BadRequestError("User is already deleted")

    # Removing your own account would leave the clinic without the admin who
    # is meant to manage it, and locks you out mid-request.
    if user.id == actor.id:
        raise BadRequestError("You cannot delete your own account")

    # A clinic admin is confined to their own clinic; super_admin operates on
    # the platform plane and does not reach into clinic staff here.
    if actor.role == UserRole.ADMIN:
        if not actor.clinic_id or user.clinic_id != actor.clinic_id:
            raise ForbiddenError("Not your clinic's user")
    else:
        raise ForbiddenError("Only a clinic administrator can delete users")

    user.deleted_at = datetime.now(UTC)
    user.is_active = False

    # Revoke live sessions, otherwise a deleted user keeps working until their
    # refresh token expires.
    await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked.is_(False),
        )
        .values(revoked=True)
    )

    await db.flush()
    await db.refresh(user)

    logger.info(
        "user_soft_deleted",
        extra={"user_id": user.id, "actor_id": actor.id},
    )

    return user

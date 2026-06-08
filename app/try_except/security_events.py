from sqlalchemy.ext.asyncio import AsyncSession
from app.try_except.audit import log_audit_event


async def log_login_success(db: AsyncSession, user_id: int):
    await log_audit_event(
        db=db,
        event_type="security",
        user_id=user_id,
        action="login_success",
        resource="auth",
    )


async def log_login_failure(db: AsyncSession, email: str):
    await log_audit_event(
        db=db,
        event_type="security",
        action="login_failure",
        resource="auth",
        status="failed",
        details={"email": email},
    )


async def log_permission_denied(
    db: AsyncSession,
    user_id: int | None,
    resource: str
):
    await log_audit_event(
        db=db,
        event_type="security",
        user_id=user_id,
        action="permission_denied",
        resource=resource,
        status="failed",
    )
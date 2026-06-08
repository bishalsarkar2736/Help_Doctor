import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.try_except.context import request_id_ctx

audit_logger = logging.getLogger("app.audit")


async def log_audit_event(
    db: AsyncSession,
    event_type: str,
    user_id: int | None = None,
    action: str | None = None,
    resource: str | None = None,
    status: str = "success",
    details: dict | None = None,
):

    audit_logger.info(
        "Audit event",
        extra={
            "event_type": event_type,
            "user_id": user_id,
            "action": action,
            "resource": resource,
            "status": status,
            "details": details or {},
        },
    )

    audit = AuditLog(
        event_type=event_type,
        user_id=user_id,
        action=action,
        resource=resource,
        status=status,
        details=details,
        request_id=request_id_ctx.get(),
    )

    db.add(audit)
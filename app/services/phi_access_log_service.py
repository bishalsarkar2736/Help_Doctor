"""Recording reads of protected health information.

Two design decisions here are deliberate, and both are trade-offs rather than
obvious choices.

**1. It writes into the request's session.**
`get_db` commits at the end of a successful request, so the row lands with the
response. This makes the log atomic with the read it describes: if the request
fails and rolls back, no access is recorded — and no access happened, because
the caller received an error rather than the data. It also matches how
`log_audit_event` already works, so there is one pattern in the codebase rather
than two.

**2. It fails open.**
If building the log entry fails, the request still succeeds. That is the wrong
default for most audit systems and the right one here: this is a clinical
system, and refusing to show a doctor a patient's allergies because an audit
row could not be constructed is a patient-safety decision, not a compliance one.

Failing open silently would be its own problem, so a failure is logged at ERROR
with the details that were meant to be persisted. Operationally, alert on this
logger — an access that was not recorded is a compliance gap even though the
request succeeded.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.phi_access_log import PHIAccessLog
from app.models.user import User, UserRole
from app.try_except.context import request_id_ctx

logger = logging.getLogger("app.phi_access")

# Roles whose reads of another person's record are worth recording. A patient
# reading their OWN record is not a disclosure and would swamp the log; that
# case is filtered below.
_LOGGED_ROLES = {
    UserRole.DOCTOR,
    UserRole.ADMIN,
    UserRole.RECEPTIONIST,
    UserRole.SUPER_ADMIN,
}

# A wide search must not write an unbounded number of rows in the request path.
_MAX_ROWS_PER_REQUEST = 100


def _role_value(actor: User) -> str:
    role = actor.role
    return role.value if hasattr(role, "value") else str(role)


async def log_phi_access(
    *,
    db: AsyncSession,
    actor: User,
    patient_id: int,
    resource_type: str,
    action: str,
    resource_id: int | None = None,
    clinic_id: int | None = None,
) -> None:
    """Record that `actor` accessed `patient_id`'s data. Never raises."""

    try:
        # Self-access is not a third-party disclosure.
        if actor.id == patient_id:
            return

        if actor.role not in _LOGGED_ROLES:
            return

        db.add(
            PHIAccessLog(
                actor_user_id=actor.id,
                # Stored as the value, not the enum, so the log says what the
                # actor WAS at the time even if the role is changed later.
                actor_role=_role_value(actor),
                clinic_id=(
                    clinic_id if clinic_id is not None else actor.clinic_id
                ),
                patient_id=patient_id,
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                request_id=request_id_ctx.get(),
            )
        )

        logger.info(
            "phi_access",
            extra={
                "actor_user_id": actor.id,
                "actor_role": _role_value(actor),
                "patient_id": patient_id,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "action": action,
            },
        )

    except Exception:
        # Deliberately swallowed — see the module docstring. Alert on this:
        # the read happened and was NOT recorded.
        logger.exception(
            "phi_access_log_failed",
            extra={
                "actor_user_id": getattr(actor, "id", None),
                "patient_id": patient_id,
                "resource_type": resource_type,
                "action": action,
            },
        )


async def log_phi_access_many(
    *,
    db: AsyncSession,
    actor: User,
    patient_ids: list[int],
    resource_type: str,
    action: str,
    clinic_id: int | None = None,
) -> None:
    """Record access to several patients at once (a list or search result).

    One row per patient, so "who accessed patient X" still finds a search that
    merely surfaced them — which is how roster-trawling shows up.
    """

    try:
        unique = [pid for pid in dict.fromkeys(patient_ids) if pid != actor.id]
        if not unique or actor.role not in _LOGGED_ROLES:
            return

        truncated = unique[:_MAX_ROWS_PER_REQUEST]
        role = _role_value(actor)
        request_id = request_id_ctx.get()
        resolved_clinic = clinic_id if clinic_id is not None else actor.clinic_id

        db.add_all(
            [
                PHIAccessLog(
                    actor_user_id=actor.id,
                    actor_role=role,
                    clinic_id=resolved_clinic,
                    patient_id=pid,
                    resource_type=resource_type,
                    resource_id=None,
                    action=action,
                    request_id=request_id,
                )
                for pid in truncated
            ]
        )

        if len(unique) > _MAX_ROWS_PER_REQUEST:
            logger.warning(
                "phi_access_log_truncated",
                extra={
                    "actor_user_id": actor.id,
                    "returned": len(unique),
                    "recorded": _MAX_ROWS_PER_REQUEST,
                },
            )

    except Exception:
        logger.exception(
            "phi_access_log_failed",
            extra={
                "actor_user_id": getattr(actor, "id", None),
                "resource_type": resource_type,
                "action": action,
                "count": len(patient_ids),
            },
        )

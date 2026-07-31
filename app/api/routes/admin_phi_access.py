"""Reading the PHI access log.

An access log nobody can query has little compliance value — the point is to be
able to answer "who looked at this patient's record?" and "what did this
clinician access?" without a DBA.

Clinic-scoped: an admin only ever sees accesses that happened in their own
clinic, enforced through resolve_clinic_id rather than a filter the caller
supplies.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.models.phi_access_log import PHIAccessLog
from app.models.user import User, UserRole
from app.schemas.phi_access import PHIAccessLogItem
from app.security.rbac import require_roles
from app.services.tenant_resolver import resolve_clinic_id

router = APIRouter(prefix="/admin/phi-access", tags=["Admin: PHI access log"])


@router.get("", response_model=list[PHIAccessLogItem])
async def list_phi_access(
    clinic_id: int,
    patient_id: int | None = Query(
        default=None, description="Everything that touched this patient"
    ),
    actor_user_id: int | None = Query(
        default=None, description="Everything this staff member accessed"
    ),
    resource_type: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    """Query the access log for one clinic.

    Note this endpoint is deliberately NOT itself PHI-logged: it returns
    identifiers and access metadata, not clinical content.
    """

    resolved_clinic_id = await resolve_clinic_id(
        db=db,
        user=admin,
        clinic_id=clinic_id,
    )

    # Columns, not entities — PHIAccessLog rows are read in bulk and the
    # response carries only scalars.
    query = (
        select(
            PHIAccessLog.id,
            PHIAccessLog.actor_user_id,
            PHIAccessLog.actor_role,
            PHIAccessLog.clinic_id,
            PHIAccessLog.patient_id,
            PHIAccessLog.resource_type,
            PHIAccessLog.resource_id,
            PHIAccessLog.action,
            PHIAccessLog.request_id,
            PHIAccessLog.created_at,
        )
        .where(PHIAccessLog.clinic_id == resolved_clinic_id)
        .order_by(PHIAccessLog.created_at.desc(), PHIAccessLog.id.desc())
    )

    if patient_id is not None:
        query = query.where(PHIAccessLog.patient_id == patient_id)

    if actor_user_id is not None:
        query = query.where(PHIAccessLog.actor_user_id == actor_user_id)

    if resource_type:
        query = query.where(PHIAccessLog.resource_type == resource_type)

    if since is not None:
        query = query.where(PHIAccessLog.created_at >= since)

    rows = (await db.execute(query.limit(limit).offset(offset))).all()

    return [
        PHIAccessLogItem(
            id=row.id,
            actor_user_id=row.actor_user_id,
            actor_role=row.actor_role,
            clinic_id=row.clinic_id,
            patient_id=row.patient_id,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            action=row.action,
            request_id=row.request_id,
            created_at=row.created_at,
        )
        for row in rows
    ]

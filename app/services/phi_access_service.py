"""PHI (patient health information) access logging.

HIPAA/GDPR expect a record of *who viewed* a patient's identifiable clinical
data, not only who changed it. This writes an access event to the clinic
activity log (action ``PHI_ACCESS``) so it surfaces in the admin Activity Log.
"""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.activity_log_service import log_activity


async def log_phi_access(
    db: AsyncSession,
    *,
    clinic_id: int | None,
    actor_id: int,
    patient_user_id: int,
    resource: str,
    resource_id: int | None = None,
) -> None:
    # Scoped to the clinic the access happened in. (For a doctor this is the
    # Doctor's clinic, which the caller resolves — the User row may not carry it.)
    if clinic_id is None:
        return

    await log_activity(
        db=db,
        clinic_id=clinic_id,
        actor_id=actor_id,
        action="PHI_ACCESS",
        entity_type="patient",
        entity_id=patient_user_id,
        details=json.dumps({"resource": resource, "resource_id": resource_id}),
    )

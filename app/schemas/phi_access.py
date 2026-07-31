from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PHIAccessLogItem(BaseModel):
    """One recorded access to a patient's protected health information."""

    model_config = ConfigDict(from_attributes=True)

    id: int

    # Who, and what they were at the time (roles change; the log does not).
    actor_user_id: int
    actor_role: str

    clinic_id: int | None

    # Whose data. References users.id, matching appointments.patient_id.
    patient_id: int

    resource_type: str
    resource_id: int | None
    action: str

    # Ties this back to the HTTP request in the structured logs.
    request_id: str | None

    created_at: datetime


class PHIAccessLogListResponse(BaseModel):
    """Paginated access log.

    Mirrors ActivityLogListResponse so the admin surfaces paginate identically.
    total_count matters more here than elsewhere: a reviewer needs to know
    whether they are looking at all of a patient's access history or the first
    page of it, and a silently truncated list is worse than no list.
    """

    items: list[PHIAccessLogItem]

    total_count: int

    limit: int

    offset: int

    has_next: bool

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ActivityLogResponse(BaseModel):

    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str
    entity_type: str
    entity_id: int | None
    actor_id: int | None
    details: str | None
    created_at: datetime


class ActivityLogListResponse(BaseModel):
    items: list[ActivityLogResponse]

    total_count: int

    limit: int

    offset: int

    has_next: bool
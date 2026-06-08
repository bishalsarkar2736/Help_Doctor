from pydantic import BaseModel
from typing import Optional


class EventActor(BaseModel):

    id: int
    role: str


class EventMetadata(BaseModel):

    schema_version: int = 1

    occurred_at: str

    correlation_id: Optional[str] = None

    causation_id: Optional[str] = None

    aggregate_type: str

    aggregate_id: int

    actor: Optional[EventActor] = None
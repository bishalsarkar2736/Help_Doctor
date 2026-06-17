from datetime import datetime
from pydantic import BaseModel


class TimelineEvent(BaseModel):
    type: str
    title: str
    reference_id: int
    occurred_at: datetime


class PatientHistoryResponse(BaseModel):
    patient_id: int

    total_count: int
    limit: int
    offset: int
    has_next: bool
    
    timeline: list[TimelineEvent]
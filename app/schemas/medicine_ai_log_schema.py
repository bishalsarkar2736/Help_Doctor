from datetime import datetime

from pydantic import BaseModel,ConfigDict


class MedicineAILogResponse(
    BaseModel
):
    
    model_config = ConfigDict(from_attributes=True)

    id: int

    medicine_id: int | None

    medicine_name: str | None

    question: str

    answer: str

    prompt_version: str

    tokens_used: int

    latency_ms: int

    created_at: datetime


class MedicineAILogStatsResponse(
    BaseModel
):
    total_queries: int

    total_tokens: int

    avg_latency_ms: float
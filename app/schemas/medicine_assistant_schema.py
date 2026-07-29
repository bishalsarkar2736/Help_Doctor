from pydantic import BaseModel


class MedicineAssistantRequest(BaseModel):
    question: str
    # Optional clinic context. Required for non-clinic-bound callers
    # (e.g. patients); ignored for doctors (resolved from their profile).
    clinic_id: int | None = None


class MedicineAssistantResponse(BaseModel):
    answer: str
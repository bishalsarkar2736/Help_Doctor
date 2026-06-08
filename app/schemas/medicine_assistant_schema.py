from pydantic import BaseModel


class MedicineAssistantRequest(BaseModel):
    question: str


class MedicineAssistantResponse(BaseModel):
    answer: str
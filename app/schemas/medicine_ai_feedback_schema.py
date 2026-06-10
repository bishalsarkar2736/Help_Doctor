from pydantic import BaseModel


class MedicineAIFeedbackCreate(
    BaseModel
):
    helpful: bool
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.doctor_document import DoctorDocumentType


class DoctorDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doctor_id: int
    doc_type: DoctorDocumentType
    original_filename: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    uploaded_at: datetime

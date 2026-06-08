from pydantic import BaseModel
from datetime import datetime


class DoctorSignatureResponse(BaseModel):

    signature_file_path: str

    signature_uploaded_at: datetime
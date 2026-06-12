from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.prescription import PrescriptionStatus


class PrescriptionVerificationResponse(
    BaseModel
):

    valid: bool

    verification_status: str

    prescription_uuid: UUID

    prescription_id: int

    appointment_id: int

    patient_id: int

    doctor_id: int

    doctor_name: str

    clinic_name: str | None = None

    clinic_logo_url: str | None = None

    status: PrescriptionStatus

    issued_at: datetime | None

    revision_number: int

    is_latest_revision: bool
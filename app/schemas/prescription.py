from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict,Field
from urllib.parse import quote
from app.models.prescription import PrescriptionStatus


class PrescriptionItemCreate(BaseModel):

    medicine_name: str
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    duration_days: Optional[int] = None
    instructions: Optional[str] = None


class PrescriptionCreate(BaseModel):

    notes: Optional[str] = None

    template_id: int | None = None

    # Set true to prescribe despite a recorded patient allergy (logged as an
    # explicit override).
    allergy_override: bool = False

    # WHY the allergy warning was overridden.
    #
    # Overriding an allergy block is among the highest-risk actions a
    # prescriber can take, and "it happened" is not an auditable record of it —
    # a safety review, an incident investigation or a regulator all ask why.
    # Required whenever the override is actually used against a real conflict
    # (enforced in the service, which is the only place that knows whether a
    # conflict exists); the minimum length keeps "x" or "ok" out of the trail.
    allergy_override_reason: Optional[str] = Field(default=None, max_length=500)

    items: list[PrescriptionItemCreate] = Field(
        default_factory=list
    )


class MedicineReference(BaseModel):

    name: str

    info_available: bool

    info_url: str

class PrescriptionItemResponse(BaseModel):

    model_config = ConfigDict(from_attributes=True)

    id: int
    medicine_name: str
    dosage: Optional[str]
    frequency: Optional[str]
    duration_days: Optional[int]
    instructions: Optional[str]

    medicine: MedicineReference | None = None



class PrescriptionResponse(BaseModel):

    model_config = ConfigDict(from_attributes=True)

    id: int

    uuid: UUID

    appointment_id: int

    doctor_id: int
    patient_id: int

    status: PrescriptionStatus

    notes: Optional[str]

    issued_at: Optional[datetime]
    created_at: datetime

    parent_prescription_id: int | None

    revision_number: int

    is_latest_revision: bool

    items: List[PrescriptionItemResponse]



class PrescriptionItemUpdate(BaseModel):

    medicine_name: str
    dosage: str | None = None
    frequency: str | None = None
    duration_days: int | None = None
    instructions: str | None = None


class PrescriptionUpdate(BaseModel):

    notes: str | None = None

    items: list[PrescriptionItemUpdate]



class PrescriptionRevisionCreate(BaseModel):

    notes: str | None = None

    template_id: int | None = None

    items: list[PrescriptionItemUpdate] = Field(
        default_factory=list
    )


class PrescriptionRevisionResponse(
    PrescriptionResponse
):
    pass



class PrescriptionRevisionHistoryItem(BaseModel):
    id: int
    uuid: UUID
    revision_number: int
    status: PrescriptionStatus
    is_latest_revision: bool
    created_at: datetime
    issued_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class PrescriptionRevisionHistoryResponse(BaseModel):
    items: list[PrescriptionRevisionHistoryItem]



class PrescriptionSearchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int

    patient_id: int
    patient_name: str | None = None

    doctor_id: int
    doctor_name: str | None = None

    status: PrescriptionStatus

    issued_at: datetime | None = None
    created_at: datetime

    medicine_names: list[str] = []

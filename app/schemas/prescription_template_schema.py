from pydantic import BaseModel,ConfigDict


class PrescriptionTemplateItemCreate(
    BaseModel,
):
    medicine_name: str
    dosage: str | None = None
    frequency: str | None = None
    duration_days: int | None = None
    instructions: str | None = None


class PrescriptionTemplateCreate(
    BaseModel,
):
    name: str
    notes: str | None = None
    items: list[
        PrescriptionTemplateItemCreate
    ]


class PrescriptionTemplateResponse(
    BaseModel,
):
    
    model_config = ConfigDict(from_attributes=True)


    id: int
    doctor_id: int
    clinic_id: int | None
    name: str
    notes: str | None

    
from pydantic import BaseModel,ConfigDict


class MedicineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    generic_name: str
    strength: str | None = None
    manufacturer: str
    category: str | None = None
    dosage_form: str | None = None
    common_use: str | None = None
    common_side_effects: str | None = None
    storage_guidance: str | None = None
    is_brand: bool


class MedicineCreate(BaseModel):
    name: str
    generic_name: str
    strength: str | None = None
    manufacturer: str

    category: str | None = None
    dosage_form: str | None = None

    common_use: str | None = None
    common_side_effects: str | None = None
    storage_guidance: str | None = None

    is_brand: bool = True


class MedicineUpdate(BaseModel):
    name: str | None = None
    generic_name: str | None = None
    strength: str | None = None
    manufacturer: str | None = None

    category: str | None = None
    dosage_form: str | None = None

    common_use: str | None = None
    common_side_effects: str | None = None
    storage_guidance: str | None = None

    is_brand: bool | None = None
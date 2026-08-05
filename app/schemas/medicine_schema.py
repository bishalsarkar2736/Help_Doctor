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


class MedicineAutocompleteItem(BaseModel):
    """One suggestion in the prescribing autocomplete.

    Narrower than MedicineResponse on purpose. This list is typed into on every
    keystroke during a consultation, so it carries only what the prescriber
    needs to choose — and `id`, which is the point: picking a suggestion stores
    the catalogue link instead of leaving downstream code to guess which row a
    typed string meant.

    generic_name is included because it is how a prescriber tells two similar
    brands apart, and it is what the allergy check actually compares.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    generic_name: str
    strength: str | None = None
    dosage_form: str | None = None
    manufacturer: str


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
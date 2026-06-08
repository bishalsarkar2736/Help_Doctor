from pydantic import BaseModel,ConfigDict



class MedicineAliasCreate(BaseModel):
    medicine_id: int
    alias: str


class MedicineAliasResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: int
    medicine_id: int
    alias: str
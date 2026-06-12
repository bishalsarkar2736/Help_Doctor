from pydantic import BaseModel,ConfigDict


class ClinicUpdate(BaseModel):

    name: str
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    primary_color: str | None = None


class ClinicResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True
    )

    id: int
    name: str

    logo_url: str | None

    address: str | None
    phone: str | None
    email: str | None
    website: str | None

    primary_color: str | None
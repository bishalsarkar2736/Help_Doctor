from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.clinic import ClinicStatus


def _validate_timezone(value: str | None) -> str | None:
    if value is None:
        return value
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        raise ValueError("Invalid IANA timezone name")
    return value


class ClinicCreate(BaseModel):
    name: str
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    primary_color: str | None = None


class ClinicUpdate(BaseModel):

    name: str
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    primary_color: str | None = None
    timezone: str | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        return _validate_timezone(v)


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

    timezone: str = "UTC"

    status: ClinicStatus = ClinicStatus.ACTIVE
    suspended_at: datetime | None = None
    deleted_at: datetime | None = None


class AdminClinicAssign(BaseModel):
    admin_id: int
    clinic_id: int


class PublicClinic(BaseModel):
    """Minimal clinic info for public directory/filters."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
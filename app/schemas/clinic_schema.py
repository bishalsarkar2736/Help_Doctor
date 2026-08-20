from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, field_validator

from app.domain.clinics.subdomain import validate_subdomain
from app.models.clinic import ClinicStatus


def _validate_timezone(value: str | None) -> str | None:
    if value is None:
        return value
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        raise ValueError("Invalid IANA timezone name")
    return value


def _validate_subdomain(value: str | None) -> str | None:
    # The rule itself lives in app/domain/clinics/subdomain.py, so the API and
    # anything else that sets this value cannot disagree about what is legal.
    # InvalidSubdomain subclasses ValueError, which pydantic already renders as
    # a 422 — no wrapping needed, and wrapping would lose the specific message.
    return validate_subdomain(value)


class ClinicCreate(BaseModel):
    name: str
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    primary_color: str | None = None

    # Optional: a clinic can be created before its DNS is decided, and most
    # are. Supplying it here saves a second call when it is already known.
    subdomain: str | None = None

    @field_validator("subdomain")
    @classmethod
    def _subdomain(cls, v: str | None) -> str | None:
        return _validate_subdomain(v)


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

    subdomain: str | None = None

    status: ClinicStatus = ClinicStatus.ACTIVE
    suspended_at: datetime | None = None
    deleted_at: datetime | None = None


class AdminClinicAssign(BaseModel):
    admin_id: int
    clinic_id: int


class ClinicSubdomainUpdate(BaseModel):
    """Changing a clinic's subdomain, and nothing else.

    Separate from ClinicUpdate for the reason given in admin_clinic.py beside
    the opening-hours endpoints, which applies harder here: ClinicUpdate
    assigns every field unconditionally, so a client that omitted `subdomain`
    would silently delete the clinic's hostname — breaking every URL already
    issued for it. A field that cannot be safely omitted does not belong on a
    schema whose other fields are optional.

    `subdomain` is required here (no default) so that clearing it is an
    explicit `null`, never an accident of omission.
    """

    subdomain: str | None

    @field_validator("subdomain")
    @classmethod
    def _subdomain(cls, v: str | None) -> str | None:
        return _validate_subdomain(v)


class PublicClinic(BaseModel):
    """Minimal clinic info for public directory/filters."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
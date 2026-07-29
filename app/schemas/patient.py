import re
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.patient import Gender

# Reasonable phone length, optionally E.164-style ("+" prefix). Matches the
# patients.phone column width (String(20)).
_PHONE_PATTERN = re.compile(r"^\+?[0-9]{7,15}$")

MAX_AGE_YEARS = 120


def _normalize_phone(value: str) -> str:
    value = value.strip()
    if not _PHONE_PATTERN.match(value):
        raise ValueError(
            "Phone must contain 7-15 digits, optionally prefixed with '+'."
        )
    return value


def _normalize_address(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Address cannot be empty.")
    return value


def _validate_date_of_birth(value: date) -> date:
    today = date.today()

    if value > today:
        raise ValueError("Date of birth cannot be in the future.")

    earliest = today.replace(year=today.year - MAX_AGE_YEARS)
    if value < earliest:
        raise ValueError(
            f"Date of birth cannot be more than {MAX_AGE_YEARS} years ago."
        )

    return value


class PatientBase(BaseModel):
    # Field length limits mirror the DB columns (String(20) / String(255));
    # safe to apply on read too since the column already caps stored data.
    phone: str = Field(max_length=20)
    address: str = Field(max_length=255)
    date_of_birth: date
    gender: Gender

    # Clinical (all optional). `allergies` is checked against prescriptions.
    allergies: str | None = None
    current_medications: str | None = None
    chronic_conditions: str | None = None
    blood_type: str | None = Field(default=None, max_length=8)
    emergency_contact_name: str | None = Field(default=None, max_length=120)
    emergency_contact_phone: str | None = Field(default=None, max_length=20)


class PatientCreate(PatientBase):
    # Content-format validators live only on the write schema so that
    # reading back pre-existing rows (PatientRead) never re-validates and
    # fails on data written before these rules existed.
    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return _normalize_phone(v)

    @field_validator("address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        return _normalize_address(v)

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, v: date) -> date:
        return _validate_date_of_birth(v)


class PatientUpdate(BaseModel):
    """PATCH — every field optional."""
    phone: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=255)
    date_of_birth: date | None = None
    gender: Gender | None = None

    allergies: str | None = None
    current_medications: str | None = None
    chronic_conditions: str | None = None
    blood_type: str | None = Field(default=None, max_length=8)
    emergency_contact_name: str | None = Field(default=None, max_length=120)
    emergency_contact_phone: str | None = Field(default=None, max_length=20)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        return _normalize_phone(v) if v is not None else v

    @field_validator("address")
    @classmethod
    def validate_address(cls, v: str | None) -> str | None:
        return _normalize_address(v) if v is not None else v

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, v: date | None) -> date | None:
        return _validate_date_of_birth(v) if v is not None else v


class PatientRead(PatientBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int

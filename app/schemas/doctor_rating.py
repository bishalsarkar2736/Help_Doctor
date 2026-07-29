"""Rating schemas.

Note which fields each audience gets — the split is the privacy design, not an
oversight:

* ``DoctorRatingSummary`` (anyone browsing doctors, and the doctor themselves)
  carries counts only. No comments, no patient identity.
* ``AdminDoctorRatingItem`` (clinic admin) carries the free text, because the
  admin is the one who acts on complaints and already has access to the
  underlying appointment.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.doctor_rating import MAX_COMMENT_LENGTH


class DoctorRatingCreate(BaseModel):
    stars: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=MAX_COMMENT_LENGTH)

    @field_validator("comment")
    @classmethod
    def normalise_comment(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        # Treat an all-whitespace comment as no comment at all.
        return cleaned or None


class DoctorRatingResponse(BaseModel):
    """The patient's own rating, echoed back to them."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    appointment_id: int
    doctor_id: int
    stars: int
    comment: str | None
    created_at: datetime
    updated_at: datetime
    editable: bool = True


class DoctorRatingSummary(BaseModel):
    """Aggregate shown publicly and to the doctor. Never includes comments."""

    doctor_id: int
    average: float | None
    count: int
    # stars value -> how many ratings gave it, always keyed "1".."5"
    distribution: dict[str, int]


class AdminDoctorRatingItem(BaseModel):
    """Clinic-admin view: the only place the written feedback is exposed."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    appointment_id: int
    doctor_id: int
    stars: int
    comment: str | None
    patient_name: str | None = None
    created_at: datetime

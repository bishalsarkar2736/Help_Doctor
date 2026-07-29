from pathlib import Path
from uuid import uuid4
from sqlalchemy import select
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.clinic import Clinic

from app.try_except.exceptions import (
    BadRequestError,
    NotFoundError,
)
from app.security.file_validation import ensure_image


UPLOAD_DIR = Path("uploads/clinic_logos")

UPLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

MAX_LOGO_SIZE_BYTES = 2 * 1024 * 1024

ALLOWED_LOGO_CONTENT_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


async def upload_clinic_logo(
    *,
    db: AsyncSession,
    clinic_id: int,
    file: UploadFile,
):

    clinic = await db.scalar(
        select(Clinic).where(
            Clinic.id == clinic_id
        )
    )

    if not clinic:
        raise NotFoundError(
            "Clinic not found"
        )

    if file.content_type not in ALLOWED_LOGO_CONTENT_TYPES:
        raise BadRequestError(
            "Only PNG, JPEG, or WEBP images are allowed"
        )

    content = await file.read()

    if len(content) > MAX_LOGO_SIZE_BYTES:
        raise BadRequestError(
            "File too large (max 2MB)"
        )

    # Never trust the client's Content-Type — verify by magic bytes.
    try:
        detected = ensure_image(content, set(ALLOWED_LOGO_CONTENT_TYPES))
    except ValueError:
        raise BadRequestError("File content is not a valid image")

    extension = ALLOWED_LOGO_CONTENT_TYPES[detected]
    file_path = UPLOAD_DIR / f"{uuid4()}{extension}"

    file_path.write_bytes(
        content
    )

    clinic.logo_url = str(
        file_path
    )

    await db.flush()

    await db.refresh(
        clinic
    )

    return {
        "logo_url":
            clinic.logo_url
    }
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.clinic_context_service import (
    get_current_clinic,
)

from app.try_except.exceptions import (
    NotFoundError,
)


UPLOAD_DIR = Path("uploads/clinic_logos")

UPLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


async def upload_clinic_logo(
    *,
    db: AsyncSession,
    file: UploadFile,
):

    clinic = await get_current_clinic(
        db
    )

    if clinic is None:
        raise NotFoundError(
            "Clinic not found"
        )

    extension = Path(
        file.filename
    ).suffix.lower()

    filename = (
        f"{uuid4()}{extension}"
    )

    file_path = (
        UPLOAD_DIR / filename
    )

    content = await file.read()

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
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.clinic import Clinic

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
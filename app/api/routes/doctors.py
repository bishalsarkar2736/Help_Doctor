from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.services.doctor_service import create_doctor_profile
from app.security.jwt import get_current_user
from app.models.user import User



router = APIRouter(prefix="/doctors", tags=["Doctors"])



@router.post("/profile")
async def create_profile(
    specialization: str,
    experience_years: int,
    bio: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await create_doctor_profile(
        db,
        current_user,
        specialization,
        experience_years,
        bio,
    )

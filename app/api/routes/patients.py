from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.postgres import get_db
from app.models.user import UserRole
from app.security.rbac import require_roles
from app.schemas.patient import PatientCreate,PatientRead
from app.services.patient_service import create_patient




router = APIRouter(prefix="/patients", tags=["patients"])





@router.post('/', response_model=PatientRead)
async def create_my_patient_profile(
    patient_in:PatientCreate,
    current_user = Depends(require_roles(UserRole.PATIENT)),
    db:AsyncSession = Depends(get_db),
):
    return await create_patient(
        db = db,
        user_id = current_user.id,
        patient_in = patient_in,
    )


@router.get("/records")
def medical_records(
    current_user = Depends(require_roles(UserRole.ADMIN, UserRole.DOCTOR))
):
    return {"message" : "Doctor/Admin access"}

from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, joinedload

from app.models.doctor import Doctor
from app.models.prescription import (
    Prescription,
    PrescriptionItem,
    PrescriptionStatus,
)
from app.models.user import User
from app.schemas.prescription import (
    PrescriptionSearchOut,
)


async def search_prescriptions(
    *,
    db: AsyncSession,
    clinic_id: int,
    patient: str | None,
    doctor: str | None,
    medication: str | None,
    status: PrescriptionStatus | None,
    issue_date: date | None,
    limit: int,
    offset: int,
) -> list[PrescriptionSearchOut]:
    stmt = (
        select(Prescription)
        .options(
            joinedload(Prescription.patient),
            joinedload(Prescription.doctor).joinedload(Doctor.user),
            joinedload(Prescription.items),
        )
        .where(
            Prescription.clinic_id == clinic_id,
        )
        .order_by(Prescription.created_at.desc())
    )

    # ----------------------------------
    # Patient (User)
    # ----------------------------------

    if patient:
        patient_user = aliased(User)

        stmt = (
            stmt.join(
                patient_user,
                Prescription.patient_id == patient_user.id,
            )
            .where(
                or_(
                    patient_user.full_name.ilike(f"%{patient}%"),
                    patient_user.email.ilike(f"%{patient}%"),
                )
            )
        )

    # ----------------------------------
    # Doctor
    # ----------------------------------

    if doctor:
        doctor_user = aliased(User)

        stmt = (
            stmt.join(
                Doctor,
                Prescription.doctor_id == Doctor.id,
            )
            .join(
                doctor_user,
                Doctor.user_id == doctor_user.id,
            )
            .where(
                or_(
                    doctor_user.full_name.ilike(f"%{doctor}%"),
                    doctor_user.email.ilike(f"%{doctor}%"),
                )
            )
        )

    # ----------------------------------
    # Medication
    # ----------------------------------

    if medication:
        stmt = (
            stmt.join(PrescriptionItem)
            .where(
                PrescriptionItem.medicine_name.ilike(
                    f"%{medication}%"
                )
            )
        )

    # ----------------------------------
    # Status
    # ----------------------------------

    if status:
        stmt = stmt.where(
            Prescription.status == status,
        )

    # ----------------------------------
    # Issue Date
    # ----------------------------------

    if issue_date:
        stmt = stmt.where(
            func.date(Prescription.issued_at) == issue_date,
        )

    stmt = (
        stmt.offset(offset)
        .limit(limit)
    )

    result = await db.execute(stmt)

    prescriptions = result.scalars().unique().all()

    return [
        PrescriptionSearchOut(
            id=p.id,
            patient_id=p.patient_id,
            patient_name=p.patient.full_name if p.patient else None,
            doctor_id=p.doctor_id,
            doctor_name=(
                p.doctor.user.full_name
                if p.doctor and p.doctor.user
                else None
            ),
            status=p.status,
            issued_at=p.issued_at,
            created_at=p.created_at,
            medicine_names=[
                item.medicine_name
                for item in p.items
            ],
        )
        for p in prescriptions
    ]
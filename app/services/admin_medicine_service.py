from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.medicine import Medicine
from app.models.prescription import PrescriptionItem
from app.schemas.medicine_schema import (
    MedicineCreate,
    MedicineUpdate,
)
from app.core.cache import delete_cache
from app.services.generic_service import resolve_or_create_generic
from app.try_except.exceptions import BadRequestError, NotFoundError


async def create_medicine(
    db: AsyncSession,
    payload: MedicineCreate,
):
    medicine = Medicine(
        **payload.model_dump()
    )

    # Linked at creation, not left for a migration to catch up on. A medicine
    # with no generic_id is invisible to substance-level allergy checking — it
    # would be flagged only when the patient's allergen matches the brand name
    # they happened to be prescribed.
    generic = await resolve_or_create_generic(
        db,
        payload.generic_name,
    )

    medicine.generic_id = generic.id if generic else None

    db.add(medicine)

    await db.flush()
    await db.refresh(medicine)

    return medicine



async def get_medicine(
    db: AsyncSession,
    medicine_id: int,
):
    result = await db.execute(
        select(Medicine).where(
            Medicine.id == medicine_id
        )
    )

    medicine = result.scalar_one_or_none()

    if not medicine:
        raise NotFoundError(
            "Medicine not found"
        )

    return medicine


async def list_medicines(
    db: AsyncSession,
):
    result = await db.execute(
        select(Medicine)
        .order_by(Medicine.name)
    )

    return result.scalars().all()



async def update_medicine(
    db: AsyncSession,
    medicine_id: int,
    payload: MedicineUpdate,
):
    medicine = await get_medicine(
        db,
        medicine_id,
    )

    old_name = medicine.name

    updates = payload.model_dump(
        exclude_unset=True
    )

    for field, value in updates.items():
        setattr(
            medicine,
            field,
            value,
        )

    # Re-derived whenever the substance is edited. Without this the displayed
    # generic_name and the generic_id the allergy check reads drift apart, and
    # the drift is silent: the admin sees the new substance while the check
    # keeps testing against the old one.
    if "generic_name" in updates:
        generic = await resolve_or_create_generic(
            db,
            updates["generic_name"],
        )

        medicine.generic_id = generic.id if generic else None

    await db.flush()
    await db.refresh(medicine)

    await delete_cache(
        f"medicine:{old_name.lower()}"
    )

    await delete_cache(
        f"medicine:{medicine.name.lower()}"
    )

    return medicine


async def delete_medicine(
    db: AsyncSession,
    medicine_id: int,
):
    medicine = await get_medicine(
        db,
        medicine_id,
    )

    # A PRESCRIBED MEDICINE IS NOT DELETABLE.
    #
    # prescription_items.medicine_id is ON DELETE SET NULL, so deleting the row
    # used to succeed quietly. Nothing clinical was lost — medicine_name is a
    # NOT NULL column on the item and is what the PDF and the API render — but
    # the route from that brand name to its active substance was: allergy
    # checking reaches the substance through Medicine -> Generic and
    # MedicineAlias -> Medicine -> Generic, and the name-matching fallback for
    # rows with no id queries the same catalogue. Deleting the row closes the id
    # path, the name path and the aliases (ON DELETE CASCADE) at once, leaving
    # the substance present in `generics` but unreachable. The next prescriber to
    # type that brand gets no substance resolved and therefore no allergy
    # conflict raised.
    #
    # Editing is the remedy and is already safe: update_medicine keeps the row,
    # so every link survives. An unreferenced medicine stays deletable, which is
    # how a genuine duplicate or typo is still removed.
    prescribed = await db.scalar(
        select(PrescriptionItem.id)
        .where(PrescriptionItem.medicine_id == medicine_id)
        .limit(1)
    )

    if prescribed is not None:
        raise BadRequestError(
            "This medicine has already been prescribed and cannot be deleted. "
            "Update the entry to correct it instead."
        )

    cache_key = (
        f"medicine:{medicine.name.lower()}"
    )

    await db.delete(medicine)

    await db.commit()

    await delete_cache(cache_key)

    return {
        "message": "Medicine deleted"
    }
from urllib.parse import quote

from app.models.prescription import Prescription

from app.schemas.prescription import (
    MedicineReference,
    PrescriptionItemResponse,
    PrescriptionResponse,
    PrescriptionRevisionResponse,
)


def build_prescription_items(
    prescription: Prescription,
    existing_medicines: set[str] | None = None,
) -> list[PrescriptionItemResponse]:

    existing_medicines = (
        existing_medicines or set()
    )

    return [
        PrescriptionItemResponse(
            id=item.id,
            medicine_name=item.medicine_name,
            medicine_id=item.medicine_id,
            dosage=item.dosage,
            frequency=item.frequency,
            duration_days=item.duration_days,
            instructions=item.instructions,
            medicine=MedicineReference(
                name=item.medicine_name,

                info_available=(
                    item.medicine_name.lower()
                    in existing_medicines
                ),

                info_url=(
                    "/medicines/search?"
                    f"name={quote(item.medicine_name)}"
                ),
            ),
        )
        for item in prescription.items
    ]


def to_prescription_response(
    prescription: Prescription,
    existing_medicines: set[str] | None = None,
) -> PrescriptionResponse:

    return PrescriptionResponse(
        id=prescription.id,
        uuid=prescription.uuid,
        appointment_id=prescription.appointment_id,
        doctor_id=prescription.doctor_id,
        patient_id=prescription.patient_id,
        status=prescription.status,
        notes=prescription.notes,
        issued_at=prescription.issued_at,
        created_at=prescription.created_at,
        parent_prescription_id=(
            prescription.parent_prescription_id
        ),
        revision_number=prescription.revision_number,
        is_latest_revision=(
            prescription.is_latest_revision
        ),
        items=build_prescription_items(
            prescription,
            existing_medicines,
        ),
    )


def to_prescription_revision_response(
    prescription: Prescription,
    existing_medicines: set[str] | None = None,
) -> PrescriptionRevisionResponse:

    return PrescriptionRevisionResponse(
        id=prescription.id,
        uuid=prescription.uuid,
        appointment_id=prescription.appointment_id,
        doctor_id=prescription.doctor_id,
        patient_id=prescription.patient_id,
        status=prescription.status,
        notes=prescription.notes,
        issued_at=prescription.issued_at,
        created_at=prescription.created_at,
        parent_prescription_id=(
            prescription.parent_prescription_id
        ),
        revision_number=prescription.revision_number,
        is_latest_revision=(
            prescription.is_latest_revision
        ),
        items=build_prescription_items(
            prescription,
            existing_medicines,
        ),
    )
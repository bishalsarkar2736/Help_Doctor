from app.models.prescription import (
    Prescription,
    PrescriptionStatus,
)

from app.try_except.exceptions import (
    BadRequestError,
)


def ensure_prescription_editable(
    prescription: Prescription,
):
    if (
        prescription.status
        != PrescriptionStatus.DRAFT
    ):
        raise BadRequestError(
            "Only draft prescriptions can be modified"
        )


def ensure_prescription_issuable(
    prescription: Prescription,
):
    if (
        prescription.status
        != PrescriptionStatus.DRAFT
    ):
        raise BadRequestError(
            "Prescription already issued"
        )

    
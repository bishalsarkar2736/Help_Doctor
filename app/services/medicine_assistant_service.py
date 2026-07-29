from sqlalchemy.ext.asyncio import AsyncSession

from app.services.medicine_matcher_service import (
    match_medicine,
)

from app.services.medicine_assistant_query_service import (
    log_medicine_assistant_query,
)

from app.core.metrics import (
    medicine_assistant_not_found_total,
    medicine_assistant_queries_total,
    medicine_assistant_success_total,
)

from app.config import get_settings
from app.services.medicine_ai_service import (
    MedicineAIService,
)

DISCLAIMER = (
    " This information is for educational purposes "
    "only and is not a substitute for professional "
    "medical advice."
)


async def answer_medicine_question(
    db: AsyncSession,
    *,
    clinic_id: int,
    question: str,
) -> str:

    medicine_assistant_queries_total.inc()

    question_lower = question.lower()

    medicine = await match_medicine(
        db,
        question,
    )

    await log_medicine_assistant_query(
        db,
        clinic_id=clinic_id,
        question=question,
        medicine_name=(
            medicine.name
            if medicine
            else None
        ),
    )

    if not medicine:

        medicine_assistant_not_found_total.inc()

        return (
            "Sorry, I could not find information "
            "about that medicine."
        )
    
    medicine_assistant_success_total.inc()

    if get_settings().ENABLE_MEDICINE_AI:

        ai_service = MedicineAIService()

        return await ai_service.answer(
            db=db,
            clinic_id=clinic_id,
            medicine=medicine,
            question=question,
        )

    # ====================================
    # MANUFACTURER
    # ====================================

    if any(
        keyword in question_lower
        for keyword in [
            "manufacturer",
            "manufacture",
            "manufactured",
            "company",
            "makes",
            "made by",
            "producer",
        ]
    ):
        return (
            f"{medicine.name} is manufactured by "
            f"{medicine.manufacturer}."
            f"{DISCLAIMER}"
        )

    # ====================================
    # GENERIC NAME
    # ====================================

    if any(
        keyword in question_lower
        for keyword in [
            "generic",
            "generic name",
        ]
    ):

        if not medicine.generic_name:
            return (
                f"Generic name information is not "
                f"available for {medicine.name}."
                f"{DISCLAIMER}"
            )

        return (
            f"The generic name of "
            f"{medicine.name} is "
            f"{medicine.generic_name}."
            f"{DISCLAIMER}"
        )

    # ====================================
    # BRAND / GENERIC
    # ====================================

    if any(
        keyword in question_lower
        for keyword in [
            "brand",
            "generic medicine",
        ]
    ):

        medicine_type = (
            "a brand medicine"
            if medicine.is_brand
            else "a generic medicine"
        )

        return (
            f"{medicine.name} is "
            f"{medicine_type}."
            f"{DISCLAIMER}"
        )

    # ====================================
    # STRENGTH
    # ====================================

    if any(
        keyword in question_lower
        for keyword in [
            "strength",
            "mg",
            "dose",
        ]
    ):

        if not medicine.strength:
            return (
                f"Strength information is not "
                f"available for {medicine.name}."
                f"{DISCLAIMER}"
            )

        return (
            f"{medicine.name} strength is "
            f"{medicine.strength}."
            f"{DISCLAIMER}"
        )

    # ====================================
    # CATEGORY
    # ====================================

    if any(
        keyword in question_lower
        for keyword in [
            "category",
            "type",
        ]
    ):

        if not medicine.category:
            return (
                f"Category information is not "
                f"available for {medicine.name}."
                f"{DISCLAIMER}"
            )

        return (
            f"{medicine.name} belongs to the "
            f"{medicine.category} category."
            f"{DISCLAIMER}"
        )

    # ====================================
    # COMMON USE
    # ====================================

    if any(
        keyword in question_lower
        for keyword in [
            "use",
            "used for",
            "purpose",
        ]
    ):

        if not medicine.common_use:
            return (
                f"Common use information is not "
                f"available for {medicine.name}."
                f"{DISCLAIMER}"
            )

        return (
            f"{medicine.name} is commonly used for "
            f"{medicine.common_use}."
            f"{DISCLAIMER}"
        )

    # ====================================
    # SIDE EFFECTS
    # ====================================

    if any(
        keyword in question_lower
        for keyword in [
            "side effect",
            "side effects",
        ]
    ):

        if not medicine.common_side_effects:
            return (
                f"Side effect information is not "
                f"available for {medicine.name}."
                f"{DISCLAIMER}"
            )

        return (
            f"Common side effects of "
            f"{medicine.name} include "
            f"{medicine.common_side_effects}."
            f"{DISCLAIMER}"
        )

    # ====================================
    # DOSAGE FORM
    # ====================================

    if any(
        keyword in question_lower
        for keyword in [
            "tablet",
            "capsule",
            "form",
            "dosage form",
        ]
    ):

        if not medicine.dosage_form:
            return (
                f"Dosage form information is not "
                f"available for {medicine.name}."
                f"{DISCLAIMER}"
            )

        return (
            f"{medicine.name} is available as "
            f"{medicine.dosage_form}."
            f"{DISCLAIMER}"
        )

    # ====================================
    # STORAGE
    # ====================================

    if any(
        keyword in question_lower
        for keyword in [
            "store",
            "storage",
        ]
    ):

        if not medicine.storage_guidance:
            return (
                f"Storage guidance is not available "
                f"for {medicine.name}."
                f"{DISCLAIMER}"
            )

        return (
            f"Storage guidance for "
            f"{medicine.name}: "
            f"{medicine.storage_guidance}."
            f"{DISCLAIMER}"
        )

    # ====================================
    # DEFAULT RESPONSE
    # ====================================

    return (
        f"{medicine.name} "
        f"{f'({medicine.strength}) ' if medicine.strength else ''}"
        f"is manufactured by "
        f"{medicine.manufacturer}. "
        f"It contains "
        f"{medicine.generic_name}. "
        f"It is commonly used for "
        f"{medicine.common_use or 'medical purposes'}."
        f"{DISCLAIMER}"
    )
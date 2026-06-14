from sqlalchemy.sql import Select


def apply_clinic_filter(
    stmt: Select,
    *,
    clinic_id: int | None,
    model,
):
    if clinic_id is None:
        return stmt

    return stmt.where(
        model.clinic_id == clinic_id
    )
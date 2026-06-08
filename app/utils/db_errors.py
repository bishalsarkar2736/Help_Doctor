from sqlalchemy.exc import IntegrityError


def is_latest_revision_conflict(
    error: IntegrityError,
) -> bool:

    return (
        "one_latest_prescription_per_appointment"
        in str(error.orig)
    )
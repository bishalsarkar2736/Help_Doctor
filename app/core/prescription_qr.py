from app.config import get_settings

settings = get_settings()


def build_prescription_verification_url(
    prescription_uuid: str,
) -> str:
    """
    Public verification URL embedded in QR.
    """

    return (
        f"{settings.BASE_URL}"
        f"/prescriptions/verify/"
        f"{prescription_uuid}"
    )
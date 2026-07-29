from app.config import get_settings

settings = get_settings()


def build_prescription_verification_url(
    prescription_uuid: str,
) -> str:
    """
    Public verification URL embedded in the prescription QR code.

    Points at the FRONTEND, not the API: whoever scans this (a pharmacist,
    usually) needs a readable page. The page then calls
    GET /prescriptions/verify/{uuid} itself. Pointing the QR straight at the
    API would show them raw JSON.
    """

    return (
        f"{settings.FRONTEND_URL}"
        f"/verify/"
        f"{prescription_uuid}"
    )
from fastapi import HTTPException, status
from google.oauth2 import id_token
from google.auth.transport import requests

from app.config import get_settings

settings = get_settings()


GOOGLE_ISSUERS = {
    "accounts.google.com",
    "https://accounts.google.com",
}


def verify_google_token(token: str) -> dict:
    """
    Verify Google ID Token.

    Returns:
        {
            "email": str,
            "full_name": str | None,
            "google_id": str,
        }
    """

    try:
        idinfo = id_token.verify_oauth2_token(
            token,
            requests.Request(),
            settings.GOOGLE_CLIENT_ID,
        )

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google token",
        )

    # Verify issuer
    if idinfo.get("iss") not in GOOGLE_ISSUERS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google issuer",
        )

    # Email must exist
    email = idinfo.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google account has no email",
        )

    # Email must be verified by Google
    if not idinfo.get("email_verified", False):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google email is not verified",
        )

    return {
        "email": email,
        "full_name": idinfo.get("name"),
        "google_id": idinfo["sub"],
    }
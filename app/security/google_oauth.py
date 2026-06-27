from fastapi import HTTPException,status
from google.oauth2 import id_token
from google.auth.transport import requests

from app.config import get_settings

settings = get_settings()


def verify_google_token(token:str) -> dict:
    """
    Verify Google ID token and return user info
    """
    try:
        idinfo = id_token.verify_oauth2_token(
            token,
            requests.Request(),
            settings.GOOGLE_CLIENT_ID
        )

        return {
            "email" : idinfo["email"],
            "full_name": idinfo.get("name"),
            "google_id" : idinfo["sub"],
        }
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google token",
        )
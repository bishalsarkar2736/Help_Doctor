"""TOTP-based multi-factor authentication helpers.

Uses pyotp for the standard TOTP algorithm (compatible with Google
Authenticator, Authy, 1Password, etc.) and qrcode to render the enrollment QR.
"""

import base64
from io import BytesIO

import pyotp
import qrcode

ISSUER = "HelpDoctor"


def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, account_name: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(
        name=account_name,
        issuer_name=ISSUER,
    )


def verify_code(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    # valid_window=1 tolerates one 30s step of clock drift.
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)


def qr_data_uri(uri: str) -> str:
    """Return a data: URI PNG of the provisioning URI for inline display."""
    img = qrcode.make(uri)
    buf = BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"

"""Encrypting sensitive column values at rest.

Currently used for users.mfa_secret. A TOTP secret is not a password: it is a
symmetric seed, so anyone holding it can generate valid codes forever. Stored
in plaintext it means a single database read — a leaked dump, a stolen backup,
an over-broad support query — silently defeats every second factor in the
system, and nothing in the audit trail would show it happened.

Fernet (AES-128-CBC + HMAC-SHA256) via a SQLAlchemy TypeDecorator, so
encryption happens in the mapper and no call site changes. app/api/routes/auth.py
still reads and writes `current_user.mfa_secret` as a plain string.

KEY MANAGEMENT
--------------
MFA_SECRET_ENCRYPTION_KEYS is a comma-separated list of urlsafe-base64 Fernet
keys. The FIRST is used to encrypt; ALL are tried when decrypting, which is
what makes rotation possible:

    1. prepend a new key      -> new writes use it, old values still readable
    2. re-save the old values -> everything now uses the new key
    3. drop the old key

If it is unset the key is derived from JWT_SECRET_KEY with HKDF, domain
separated by a distinct info string so it is not literally the signing key.
That keeps the default deployment working without new required config, but it
couples the two: **rotating JWT_SECRET_KEY makes every stored MFA secret
undecryptable and locks those users out of their second factor.** Set a
dedicated key before you ever rotate the JWT secret.

Generate one with:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

import base64
import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

logger = logging.getLogger(__name__)

# Every Fernet token starts with version byte 0x80, which is "gAAAAA" once
# urlsafe-base64 encoded. Used to tell "this is ciphertext we failed to
# decrypt" (a key problem — fail loudly) from "this is a legacy plaintext
# value written before encryption existed" (read it, re-encrypt on next write).
_FERNET_PREFIX = "gAAAAA"

_fernet: MultiFernet | None = None


def _derive_key_from(secret: str) -> bytes:
    """HKDF a Fernet key from another secret, domain-separated by `info`."""
    raw = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"helpdoctor.field_encryption.mfa_secret.v1",
    ).derive(secret.encode())

    return base64.urlsafe_b64encode(raw)


def get_fernet() -> MultiFernet:
    global _fernet

    if _fernet is None:
        from app.config import get_settings

        settings = get_settings()
        configured = [
            k.strip()
            for k in settings.MFA_SECRET_ENCRYPTION_KEYS.split(",")
            if k.strip()
        ]

        if configured:
            keys = [Fernet(k) for k in configured]
        else:
            logger.warning(
                "mfa_secret_encryption_key_derived_from_jwt_secret",
                extra={
                    "detail": (
                        "MFA_SECRET_ENCRYPTION_KEYS is unset; deriving from "
                        "JWT_SECRET_KEY. Rotating the JWT secret will make "
                        "stored MFA secrets undecryptable."
                    )
                },
            )
            keys = [Fernet(_derive_key_from(settings.JWT_SECRET_KEY))]

        _fernet = MultiFernet(keys)

    return _fernet


def reset_fernet() -> None:
    """Drop the cached instance. For tests and key changes."""
    global _fernet
    _fernet = None


class EncryptedSecret(TypeDecorator):
    """A string column encrypted at rest, transparent to the application.

    Note this makes the column unsearchable: ciphertext differs every time
    (Fernet includes a random IV), so equality lookups and indexes on it are
    meaningless. That is fine for mfa_secret, which is only ever read via the
    owning user row — check before applying this to a column you filter on.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None

        return get_fernet().encrypt(value.encode()).decode()

    def process_result_value(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None

        if not value.startswith(_FERNET_PREFIX):
            # Written before this column was encrypted. Return it so the user
            # is not locked out; it is re-encrypted the next time it is saved.
            logger.warning("encrypted_field_plaintext_value_read")
            return value

        try:
            return get_fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            # Ciphertext we cannot decrypt means the key is wrong or missing.
            # Returning it raw would hand the caller a useless string that
            # silently fails every TOTP check; better to fail where the cause
            # is obvious.
            logger.error("encrypted_field_undecryptable")
            raise ValueError(
                "Stored value could not be decrypted — check "
                "MFA_SECRET_ENCRYPTION_KEYS (was JWT_SECRET_KEY rotated?)"
            )

"""Short-lived, revocable signed URLs for stored files that must not be public.

WHY THIS EXISTS
A doctor's signature was served to anyone at media/signatures/doctor_<id>.png.
The id is a sequential primary key, so the whole set was enumerable by counting,
and the signature is the mark that authenticates a prescription.

WHY NOT JUST REQUIRE AUTHENTICATION
The browser loads the signature as an <img> tag, and an image request carries no
Authorization header. HTTP auth here is OAuth2PasswordBearer (security/jwt.py) —
header only, no access-token cookie — so a plain role gate would break the
doctor's own credentials page. A capability in the URL is what an <img> can
actually present.

WHY NOT PUT THE ACCESS TOKEN IN THE URL
decode_token_from_ws accepts ?token= for websockets, so the precedent exists,
but a session token in an image URL lands in access logs, proxy logs and Referer
headers, and it grants everything the session can do rather than one file.

THE CONTRACT
    media/signatures/doctor_7.png?exp=1771200000&v=3&sig=<urlsafe-b64>

The MAC is HMAC-SHA256 over a canonical newline-joined record:

    "v2" \n <file key> \n <expiry> \n <access version>

Newline-joined rather than concatenated, because no field can contain a newline:
plain concatenation would let ("media/a", 12) and ("media/a1", 2) produce the
same MAC input. The leading scheme label means a future format cannot be
reinterpreted as this one. Every field is therefore bound — repointing the key at
another doctor's signature, pushing `exp` further out, or editing `v` all
invalidate the MAC.

The MAC is computed over the parameter strings EXACTLY as they travel, not over
reparsed integers. That costs nothing and removes malleability: "01" and "1" are
different messages, so there is one valid URL per capability rather than a family
of equivalent ones.

REVOCATION
Signing is stateless — no row is written per URL, and none is read to verify one.
That is what avoids a token table on a read path, but it means a minted URL
cannot be withdrawn by forgetting it. So the URL carries the doctor's
`signature_access_version`, and the serving route (app/api/routes/files.py)
refuses any URL whose version is not the doctor's current one. Uploading a
signature bumps that column, which invalidates every outstanding URL for the
previous image immediately rather than one TTL later.

Verification here is deliberately the stateless half only: MAC, then expiry. The
version is returned for the caller to compare against the database, so the
ordering — cheap constant-time checks first, database read only for a request
that has already proved it holds a real MAC — stays visible at the call site.

KEY MANAGEMENT
The signing key is HKDF-derived from JWT_SECRET_KEY, domain-separated by a
distinct `info` string, exactly as security/field_encryption.py derives its
fallback key. That keeps this working with no new required configuration, at the
cost of coupling: rotating JWT_SECRET_KEY invalidates every outstanding signed
URL. Unlike the MFA case that is harmless — the URLs last minutes, and the
frontend mints a fresh one on the next profile load.
"""

from __future__ import annotations

import base64
import hmac
from hashlib import sha256

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.time import utc_now

# Distinct from field_encryption's info string: the two keys must not be equal.
_HKDF_INFO = b"helpdoctor.file_urls.signed_key.v1"

# Inside the MAC, so a differently-shaped future record cannot be replayed as
# this one. Bumping it invalidates every outstanding URL, by design.
_SCHEME = "v2"

EXPIRY_PARAM = "exp"
SIGNATURE_PARAM = "sig"
VERSION_PARAM = "v"

_signing_key: bytes | None = None


def _derive_signing_key() -> bytes:
    from app.config import get_settings

    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=_HKDF_INFO,
    ).derive(get_settings().JWT_SECRET_KEY.encode())


def get_signing_key() -> bytes:
    """Cached: HKDF on every mint and verify is waste, and get_settings() is
    itself lru_cached, so the config this derives from is already fixed for the
    life of the process."""
    global _signing_key

    if _signing_key is None:
        _signing_key = _derive_signing_key()

    return _signing_key


def _mac(key: str, expires_at: str, access_version: str) -> str:
    message = "\n".join((_SCHEME, key, expires_at, access_version)).encode()

    digest = hmac.new(get_signing_key(), message, sha256).digest()

    # urlsafe alphabet, padding stripped: safe to drop into a query string with
    # no escaping, and no "=" for a proxy to mangle.
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def sign_key(
    key: str,
    *,
    access_version: int,
    ttl_seconds: int | None = None,
) -> str:
    """Return `key` with expiry, version and signature query parameters.

    `access_version` is required rather than defaulted: a URL signed at the wrong
    version is refused at serve time, so silently guessing it would turn a
    caller's oversight into a broken image instead of a type error.

    The result is relative, matching what doctors.signature_file_path already
    held, so callers that build `${apiUrl}/${path}` keep working unchanged.
    """
    if ttl_seconds is None:
        from app.config import get_settings

        ttl_seconds = get_settings().SIGNED_FILE_URL_TTL_SECONDS

    expires_at = str(int(utc_now().timestamp()) + ttl_seconds)
    version = str(access_version)

    return (
        f"{key}"
        f"?{EXPIRY_PARAM}={expires_at}"
        f"&{VERSION_PARAM}={version}"
        f"&{SIGNATURE_PARAM}={_mac(key, expires_at, version)}"
    )


def verify_signed_key(
    key: str,
    expires_at: str | None,
    signature: str | None,
    access_version: str | None,
) -> int | None:
    """The stateless half of authorising a signed URL.

    Returns the access version the URL was signed at — which the caller must
    still compare against the doctor's current version — or None if the URL is
    not authentic or has expired. Callers must test `is None`, not falsiness.

    Total: every malformed input is a None rather than an exception, because
    these values come straight off an unauthenticated query string and a
    traceback here would be a 500 anyone could trigger.
    """
    if not expires_at or not signature or not access_version:
        return None

    # Signature first, over the raw strings. Checking expiry or version first
    # would answer questions about a MAC the caller has not proved they hold.
    if not hmac.compare_digest(
        _mac(key, expires_at, access_version), signature
    ):
        return None

    try:
        deadline = int(expires_at)
        version = int(access_version)
    except ValueError:
        # Unreachable for anything this module signed, since both fields are
        # produced from ints. Kept so a malformed value can never be an
        # exception, whatever signs a URL in future.
        return None

    if int(utc_now().timestamp()) > deadline:
        return None

    return version

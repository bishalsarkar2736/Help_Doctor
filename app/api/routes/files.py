"""Serving stored files through the storage seam.

Replaces `app.mount("/media", StaticFiles(directory="media"))`. That mount
reads the local filesystem directly, so it silently serves nothing once
STORAGE_BACKEND=s3 — every doctor signature in the UI would become a broken
image, and prescription PDFs would render unsigned.

Going through get_storage() means the same URLs work under either backend.

TWO CLASSES OF FILE, AND A DELIBERATELY NARROW ALLOWLIST
--------------------------------------------------------
SIGNED_PREFIXES needs a valid, unexpired, current-version signature on the URL.
Doctor signatures live here. They used to be public, which meant the mark that
authenticates a prescription was downloadable by anyone who could count: the key
is media/signatures/doctor_<id>.png and the id is a sequential primary key, so
the whole set was enumerable. A signed URL is what an <img> tag can present,
because an image request carries no Authorization header — see
app/security/file_urls.py for why not a role gate and not a JWT in the URL.

PUBLIC_PREFIXES stays genuinely open. A clinic logo is public branding, shown to
anonymous visitors browsing clinics, and the frontend builds
`${apiUrl}${logo_url}` with no credentials to offer.

Anything in NEITHER tuple is not served here at all. Doctor credential documents
— BMDC certificates, medical licences — live under uploads/doctor_documents/ and
stay behind the authenticated, clinic-scoped route in admin_doctors.py. A blanket
`/uploads` mount would have exposed every practitioner's identity documents to
anyone who could guess a filename.

ORDER OF CHECKS IS THE SECURITY PROPERTY
----------------------------------------
For a signature: MAC, then expiry, then the doctor's current access version,
and only then the storage read. Two things fall out of that ordering.

An unsigned or forged request never reaches the database or storage, so it
cannot be used to probe which keys exist and cannot be turned into load by
anyone who can type a URL.

And because the MAC is checked before anything is looked up, every refusal can
share one 403 with one message without leaking whether the key, the doctor or
the file existed.
"""

import re

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.models.doctor import Doctor
from app.security.file_urls import verify_signed_key
from app.services.storage import get_storage
from app.try_except.exceptions import ForbiddenError, NotFoundError

router = APIRouter(tags=["Files"])

# Reachable only with a valid signature from app.security.file_urls.
SIGNED_PREFIXES = ("media/signatures/",)

# Reachable by anyone. Public by intent, not by omission.
PUBLIC_PREFIXES = ("uploads/clinic_logos/",)

# The exact shape doctor_service writes, and nothing else. A full match, so no
# signature key can contain a path separator or a "..": traversal is refused
# here, before storage is consulted, rather than relying on the storage root
# guard to catch it afterwards. That guard stays as defence in depth
# (LocalFilesystemStorage._resolve, tests/api/test_storage.py).
_SIGNATURE_KEY = re.compile(r"^media/signatures/doctor_(\d+)\.(?:png|jpe?g)$")

_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
}

# One message for every refusal on the signed path — see the module docstring.
_REFUSED = "File access requires a valid signed URL"


def _content_type(key: str) -> str:
    for suffix, media_type in _CONTENT_TYPES.items():
        if key.lower().endswith(suffix):
            return media_type
    return "application/octet-stream"


async def _authorize_signature(
    db: AsyncSession,
    key: str,
    *,
    expires_at: str | None,
    signature: str | None,
    access_version: str | None,
) -> None:
    """Raise unless the URL is authentic, unexpired and at the current version."""

    signed_version = verify_signed_key(
        key, expires_at, signature, access_version
    )

    # `is None`, not falsiness: version 0 would be a legitimate value.
    if signed_version is None:
        raise ForbiddenError(_REFUSED)

    doctor_id = _SIGNATURE_KEY.match(key)

    if doctor_id is None:
        # A validly signed key that is not a signature key. Nothing mints these,
        # so reaching here means either the signing key leaked or something new
        # signs caller-controlled input — refuse rather than read it.
        raise ForbiddenError(_REFUSED)

    current_version = await db.scalar(
        select(Doctor.signature_access_version).where(
            Doctor.id == int(doctor_id.group(1))
        )
    )

    # None covers the deleted doctor: fail closed rather than serving a
    # signature whose owner no longer exists.
    if current_version is None or current_version != signed_version:
        raise ForbiddenError(_REFUSED)


def _read(key: str) -> Response:
    storage = get_storage()

    try:
        data = storage.read(key)
    except (FileNotFoundError, ValueError):
        # ValueError is the storage root-escape guard. Independent of every
        # check above: a signature proves a URL came from us, never that it may
        # address something outside the storage root.
        raise NotFoundError("File not found")

    return Response(
        content=data,
        media_type=_content_type(key),
        headers={
            # Content-addressed these are not — a doctor can replace their
            # signature at the same key — so cache briefly rather than forever.
            "Cache-Control": "private, max-age=300",
            # The bytes are user-uploaded; never let a browser sniff them into
            # something executable.
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/media/{path:path}")
async def get_media(
    path: str,
    exp: str | None = Query(
        default=None,
        description="Signed URL expiry, seconds since the epoch",
    ),
    v: str | None = Query(
        default=None,
        description="Signature access version the URL was minted at",
    ),
    sig: str | None = Query(
        default=None,
        description="Signature over the key, expiry and version",
    ),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Doctor signatures. Requires a signed URL — see SIGNED_PREFIXES."""

    key = f"media/{path}"

    if key.startswith(SIGNED_PREFIXES):
        await _authorize_signature(
            db, key, expires_at=exp, signature=sig, access_version=v
        )
    elif not key.startswith(PUBLIC_PREFIXES):
        # 404 rather than 403: whether a given private key exists is itself
        # information, and this router should look like it serves nothing else.
        raise NotFoundError("File not found")

    return _read(key)


@router.get("/uploads/{path:path}")
async def get_upload(path: str) -> Response:
    """Clinic logos only — see PUBLIC_PREFIXES.

    There was previously no route here at all, so clinic_logo_service wrote
    files to uploads/clinic_logos/ that nothing could ever serve: the frontend
    builds `${apiUrl}${logo_url}` from the stored path and would have received
    a 404 for every uploaded logo. Latent only because no clinic had set one.

    No signature parameters and no database session: nothing served here is
    private, and accepting either would imply otherwise.
    """
    key = f"uploads/{path}"

    if not key.startswith(PUBLIC_PREFIXES):
        raise NotFoundError("File not found")

    return _read(key)

"""Serving stored files through the storage seam.

Replaces `app.mount("/media", StaticFiles(directory="media"))`. That mount
reads the local filesystem directly, so it silently serves nothing once
STORAGE_BACKEND=s3 — every doctor signature in the UI would become a broken
image, and prescription PDFs would render unsigned.

Going through get_storage() means the same URLs work under either backend.

PUBLIC BY DESIGN, AND DELIBERATELY NARROW
-----------------------------------------
These paths are unauthenticated, because the browser loads them as <img> tags
and image requests carry no Authorization header. That was already true of the
StaticFiles mount this replaces.

So the allowlist matters: only signatures and clinic logos are reachable here.
Doctor credential documents — BMDC certificates, medical licences — live under
uploads/doctor_documents/ and are NOT served by this router. They stay behind
the authenticated, clinic-scoped route in admin_doctors.py. A blanket
`/uploads` mount would have exposed every practitioner's identity documents to
anyone who could guess a filename.

Note that signatures remain effectively public to anyone holding the URL, which
is unchanged from before but worth knowing: the filenames are predictable
(doctor_<id>.png). Making them unguessable would mean moving to random keys, a
data migration, and is tracked separately.
"""

from fastapi import APIRouter, Response

from app.services.storage import get_storage
from app.try_except.exceptions import NotFoundError

router = APIRouter(tags=["Files"])

# Prefixes reachable without authentication. Anything not listed here is not
# served by this router at all.
PUBLIC_PREFIXES = (
    "media/signatures/",
    "uploads/clinic_logos/",
)

_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
}


def _content_type(key: str) -> str:
    for suffix, media_type in _CONTENT_TYPES.items():
        if key.lower().endswith(suffix):
            return media_type
    return "application/octet-stream"


def _serve(key: str) -> Response:
    if not key.startswith(PUBLIC_PREFIXES):
        # 404 rather than 403: whether a given private key exists is itself
        # information, and this router should look like it serves nothing else.
        raise NotFoundError("File not found")

    storage = get_storage()

    try:
        data = storage.read(key)
    except (FileNotFoundError, ValueError):
        # ValueError is the storage root-escape guard — a key like
        # "media/signatures/../../etc/passwd" must read as "not found".
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
async def get_media(path: str) -> Response:
    """Doctor signatures. Previously the StaticFiles mount."""
    return _serve(f"media/{path}")


@router.get("/uploads/{path:path}")
async def get_upload(path: str) -> Response:
    """Clinic logos only — see PUBLIC_PREFIXES.

    There was previously no route here at all, so clinic_logo_service wrote
    files to uploads/clinic_logos/ that nothing could ever serve: the frontend
    builds `${apiUrl}${logo_url}` from the stored path and would have received
    a 404 for every uploaded logo. Latent only because no clinic had set one.
    """
    return _serve(f"uploads/{path}")

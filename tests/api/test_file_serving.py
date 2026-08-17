"""Serving stored files through the storage seam.

These replaced `app.mount("/media", StaticFiles(directory="media"))`, which
reads the local filesystem directly and would serve nothing once
STORAGE_BACKEND=s3.

The allowlist is the security-critical part, and it now has two tiers.
Signatures need a signed URL carrying the doctor's current access version
(SIGNED_PREFIXES); clinic logos stay public (PUBLIC_PREFIXES); doctor credential
documents — BMDC certificates and medical licences — live under uploads/
alongside clinic logos and are in neither tuple, so they must NOT be reachable
here at all.

Signature tests use a real Doctor row rather than a hardcoded doctor_1, because
serving now resolves the doctor from the key to compare access versions. The
authorization rules themselves live in
tests/security/test_signature_requires_authorization.py.
"""

import pytest

from app.security.file_urls import sign_key
from app.services.storage import LocalFilesystemStorage, set_storage

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def storage(tmp_path):
    backend = LocalFilesystemStorage(root=tmp_path)
    set_storage(backend)
    try:
        yield backend
    finally:
        set_storage(None)


def _signed(doctor) -> str:
    key = f"media/signatures/doctor_{doctor.id}.png"
    return sign_key(key, access_version=doctor.signature_access_version)


@pytest.mark.asyncio
async def test_signature_is_served_through_a_signed_url(client, storage, doctor):
    storage.write(f"media/signatures/doctor_{doctor.id}.png", PNG)

    res = await client.get(f"/{_signed(doctor)}")

    assert res.status_code == 200, res.text
    assert res.content == PNG
    assert res.headers["content-type"] == "image/png"


@pytest.mark.asyncio
async def test_signature_needs_no_authorization_header(client, storage, doctor):
    """The capability is in the URL, because <img> tags cannot send one.

    This is what the signature mechanism buys: the doctor's own credentials page
    keeps working with an ordinary <img src=...>, while the key on its own is
    worthless. It replaces test_signature_is_public, which asserted that the
    bare key was enough — the behaviour removed in the Finding 8 fix.
    """
    key = f"media/signatures/doctor_{doctor.id}.png"
    storage.write(key, PNG)

    signed = await client.get(f"/{_signed(doctor)}")
    assert signed.status_code == 200
    assert "authorization" not in {h.lower() for h in signed.request.headers}

    bare = await client.get(f"/{key}")
    assert bare.status_code == 403
    assert bare.content != PNG


@pytest.mark.asyncio
async def test_clinic_logo_is_served(client, storage):
    """There was previously no /uploads route at all.

    clinic_logo_service wrote files that nothing could serve: the frontend
    builds `${apiUrl}${logo_url}` from the stored path and got a 404 for every
    uploaded logo. Latent only because no clinic had set one.
    """
    storage.write("uploads/clinic_logos/abc.png", PNG)

    res = await client.get("/uploads/clinic_logos/abc.png")

    assert res.status_code == 200, res.text
    assert res.content == PNG


@pytest.mark.asyncio
async def test_credential_documents_are_NOT_publicly_served(client, storage):
    """The one that matters: licences must stay behind authentication.

    A blanket /uploads mount would have exposed every practitioner's identity
    documents to anyone who could guess a filename.
    """
    storage.write("uploads/doctor_documents/doctor1_bmdc_secret.pdf", b"%PDF-1.4")

    res = await client.get("/uploads/doctor_documents/doctor1_bmdc_secret.pdf")

    assert res.status_code == 404, res.text
    assert b"%PDF" not in res.content


@pytest.mark.asyncio
async def test_unknown_prefix_under_media_is_refused(client, storage):
    storage.write("media/private/secret.png", PNG)

    res = await client.get("/media/private/secret.png")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_missing_file_is_404_not_500(client, storage, doctor):
    """A fully authorised URL for a key with no file behind it is a plain 404.

    Authorised, because an unsigned request is refused before storage is ever
    consulted — that ordering is what stops the 403/404 split from leaking which
    keys exist.
    """
    res = await client.get(f"/{_signed(doctor)}")

    assert res.status_code == 404


@pytest.mark.asyncio
async def test_path_traversal_is_refused(client, storage):
    """A key escaping the storage root must never serve.

    Percent-encoded because httpx resolves a literal "../.." before sending, so
    the plain form never reaches the route and tests nothing. Refused at the
    signature gate here; the strict key pattern refuses it even when signed, and
    the storage root guard behind both is covered in test_storage.py.
    """
    res = await client.get("/media/signatures/%2e%2e/%2e%2e/etc/passwd")

    assert res.status_code == 403
    assert b"root:" not in res.content


@pytest.mark.asyncio
async def test_served_files_are_not_sniffable(client, storage, doctor):
    """The bytes are user-uploaded; never let a browser guess them executable."""
    storage.write(f"media/signatures/doctor_{doctor.id}.png", PNG)

    res = await client.get(f"/{_signed(doctor)}")
    assert res.headers.get("x-content-type-options") == "nosniff"

"""Serving stored files through the storage seam.

These replaced `app.mount("/media", StaticFiles(directory="media"))`, which
reads the local filesystem directly and would serve nothing once
STORAGE_BACKEND=s3.

The allowlist is the security-critical part: doctor credential documents —
BMDC certificates and medical licences — live under uploads/ alongside clinic
logos, and must NOT be reachable without authentication.
"""

import pytest

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


@pytest.mark.asyncio
async def test_signature_is_served(client, storage):
    storage.write("media/signatures/doctor_1.png", PNG)

    res = await client.get("/media/signatures/doctor_1.png")

    assert res.status_code == 200, res.text
    assert res.content == PNG
    assert res.headers["content-type"] == "image/png"


@pytest.mark.asyncio
async def test_signature_is_public(client, storage):
    """No Authorization header — <img> tags cannot send one."""
    storage.write("media/signatures/doctor_2.png", PNG)

    res = await client.get("/media/signatures/doctor_2.png")
    assert res.status_code == 200


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
async def test_missing_file_is_404_not_500(client, storage):
    res = await client.get("/media/signatures/nope.png")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_path_traversal_is_refused(client, storage):
    """A key escaping the storage root must read as not-found, never serve."""
    res = await client.get("/media/signatures/../../../etc/passwd")
    assert res.status_code == 404
    assert b"root:" not in res.content


@pytest.mark.asyncio
async def test_served_files_are_not_sniffable(client, storage):
    """The bytes are user-uploaded; never let a browser guess them executable."""
    storage.write("media/signatures/doctor_3.png", PNG)

    res = await client.get("/media/signatures/doctor_3.png")
    assert res.headers.get("x-content-type-options") == "nosniff"

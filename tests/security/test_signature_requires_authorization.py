"""A doctor's signature was downloadable by anyone who could count.

THE EXPOSURE THIS CLOSES
upload_doctor_signature (doctor_service.py) stores the image at

    media/signatures/doctor_<doctor.id>.png     (or .jpg)

and files.py listed "media/signatures/" as public, so the bytes went to a caller
with no credentials at all. The id is a sequential primary key, so the whole set
was enumerable by walking doctor_1, doctor_2, ...

Confirmed against the running deployment during the audit, not just inferred:
GET /media/signatures/doctor_1.png returned 200 with 243,242 bytes and no
Authorization header.

WHY IT MATTERS
The signature is the mark that authenticates a prescription. The risk is forgery
of clinic documents rather than disclosure of clinical data — nothing here
reveals a diagnosis — but a handwritten signature is also personal data in its
own right, and it was being handed to unauthenticated strangers.

THE MECHANISM THESE TESTS PIN
media/signatures/ moved from PUBLIC_PREFIXES to SIGNED_PREFIXES. A URL must now
carry `exp`, `v` and a `sig` that is HMAC-SHA256 over a canonical newline-joined
record of scheme, key, expiry and version (app/security/file_urls.py). The
capability lives in the URL because an <img> tag cannot send an Authorization
header, and the stored column still holds the bare storage key — no rename, and
no signed URL or token is persisted anywhere.

`v` is the doctor's signature_access_version, and serving compares it against the
column. That is what makes a stateless signature revocable: uploading a
replacement bumps the column and every outstanding URL for the previous image
dies at once, rather than staying good until it expires.

Five properties are what make any of this worth having, and each has a test:
  * the bare key alone is refused,
  * the MAC binds the KEY, so a signature cannot be replayed across doctors,
  * the MAC binds `exp`, so a deadline cannot be extended,
  * the MAC binds `v`, so a version cannot be edited,
  * and the version is checked against the DATABASE, so a genuinely signed URL
    at a superseded version is still refused.

The last two are separate on purpose. A test that only edits `v` proves the MAC
covers it and would still pass if the database comparison were deleted entirely.

ORDERING
MAC, then expiry, then the database version, then the storage read. So an
unsigned request touches neither the database nor storage, every refusal shares
one 403 with one message, and nothing about the 403/404 split reveals which keys
exist.

WHAT MUST NOT REGRESS
  * uploads/doctor_documents/ — BMDC certificates, medical licences — is in
    neither prefix tuple and must stay unreachable here.
  * signature keys are matched against a strict full pattern, so no signature
    key can contain a separator or "..". The storage root guard behind that
    stays as defence in depth (tests/api/test_storage.py).
  * uploads/clinic_logos/ is still genuinely public — a logo is public branding
    and the frontend renders it for anonymous visitors with no credentials.
  * PDF generation reads the bare key from storage and never a URL
    (tests/services/test_pdf_survives_bad_signature.py).

A fix that closes the signature hole by breaking clinic logos, or by loosening
the document allowlist, is not a fix.
"""

import io

import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy import select

from app.models.doctor import Doctor
from app.security.file_urls import (
    EXPIRY_PARAM,
    SIGNATURE_PARAM,
    VERSION_PARAM,
    sign_key,
)
from app.services.storage import LocalFilesystemStorage, set_storage


def real_png(size=(40, 20)) -> bytes:
    """A decodable PNG — file_validation rejects header-only fakes."""

    buf = io.BytesIO()
    Image.new("RGB", size, (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def real_jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), (200, 10, 10)).save(buf, format="JPEG")
    return buf.getvalue()


PDF = b"%PDF-1.4\n%fake credential document\n"


@pytest.fixture
def storage(tmp_path):
    """The real filesystem backend, rooted in a temp dir.

    Not a mock: the route reads through get_storage(), and the root-escape guard
    lives in LocalFilesystemStorage._resolve. Pointing the real backend at
    tmp_path keeps that logic live while writing nothing into the repository or
    the deployed volumes.
    """
    backend = LocalFilesystemStorage(root=tmp_path)
    set_storage(backend)
    try:
        yield backend
    finally:
        set_storage(None)


@pytest.fixture
def anonymous(client):
    """The client with no credentials — httpx sends no Authorization header."""

    return client


@pytest_asyncio.fixture
async def on_disk(storage, doctor):
    """A real Doctor row and a signature file at the real key.

    A real row because serving resolves the doctor from the key to compare
    access versions, so a hardcoded doctor_1 would be refused for the wrong
    reason and prove nothing.
    """
    key = f"media/signatures/doctor_{doctor.id}.png"
    image = real_png()
    storage.write(key, image)

    return {
        "doctor": doctor,
        "key": key,
        "image": image,
        "version": doctor.signature_access_version,
    }


def _params(signed_url: str) -> dict[str, str]:
    """Split a signed URL into its query parameters."""

    _, _, query = signed_url.partition("?")
    return dict(part.split("=", 1) for part in query.split("&"))


async def _upload_signature(client, auth_doctor, *, image=None, filename=None):
    """Store a signature through the real route.

    Returns (bare storage key, signed URL as the API handed it back).

    Deliberately not storage.write(...) with a hand-written key: the key
    convention and the version bump both live inside upload_doctor_signature,
    and a test that reimplemented either would keep passing if the service
    changed shape.
    """
    is_jpeg = bool(filename and filename.endswith(".jpg"))

    res = await client.post(
        "/doctors/signature",
        files={
            "file": (
                filename or "signature.png",
                image if image is not None else real_png(),
                "image/jpeg" if is_jpeg else "image/png",
            )
        },
        headers=auth_doctor["headers"],
    )

    assert res.status_code == 200, res.text

    signed = res.json()["signature_file_path"]
    return signed.partition("?")[0], signed


# ---------------------------------------------------------------------------
# The key is still guessable. That is fine now, and this states why.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_stored_key_is_still_predictable(client, storage, auth_doctor):
    """The premise of the whole file: the key is derivable from the doctor id.

    Unchanged by the fix, and deliberately so — rewriting keys would mean a data
    migration. The defence is the signature, not obscurity of the key. If this
    ever changes to random keys, the reason the rest of this file exists is
    visibly re-stated rather than silently obsolete.
    """
    key, _ = await _upload_signature(client, auth_doctor)

    doctor_id = auth_doctor["doctor"].id
    assert key == f"media/signatures/doctor_{doctor_id}.png"
    assert storage.exists(key)


@pytest.mark.asyncio
async def test_the_api_hands_back_a_signed_url_not_the_bare_key(
    client, storage, auth_doctor
):
    """The upload response is what the frontend renders, so it must be signed."""

    key, signed = await _upload_signature(client, auth_doctor)
    params = _params(signed)

    assert signed.startswith(f"{key}?")
    assert EXPIRY_PARAM in params
    assert VERSION_PARAM in params
    assert SIGNATURE_PARAM in params


@pytest.mark.asyncio
async def test_the_doctors_own_profile_hands_back_a_signed_url(
    client, storage, auth_doctor
):
    """GET /doctors/me feeds the <img> on the credentials page.

    The upload response is not the only carrier: the page also renders from the
    profile it loads on mount, so signing one and not the other would leave a
    broken image on every revisit. The version is NOT added to DoctorMe — it
    exists only to sign this URL — so the frontend contract is unchanged.
    """
    key, _ = await _upload_signature(client, auth_doctor)

    res = await client.get("/doctors/me", headers=auth_doctor["headers"])
    assert res.status_code == 200, res.text

    body = res.json()
    assert body["signature_file_path"].startswith(f"{key}?")
    assert "signature_access_version" not in body

    fetched = await client.get(f"/{body['signature_file_path']}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.content == storage.read(key)


@pytest.mark.asyncio
async def test_a_doctor_without_a_signature_gets_null_not_a_signed_nothing(
    client, storage, auth_doctor
):
    """None must stay None — there is no key to sign."""

    res = await client.get("/doctors/me", headers=auth_doctor["headers"])

    assert res.status_code == 200, res.text
    assert res.json()["signature_file_path"] is None


# ---------------------------------------------------------------------------
# Accepted: a valid signed URL at the current version.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_valid_signed_url_serves_the_signature(on_disk, anonymous):
    """The legitimate path, with no Authorization header anywhere."""

    signed = sign_key(on_disk["key"], access_version=on_disk["version"])

    res = await anonymous.get(f"/{signed}")

    assert res.status_code == 200, res.text
    assert res.content == on_disk["image"]
    assert res.headers["content-type"] == "image/png"
    assert res.headers.get("x-content-type-options") == "nosniff"


@pytest.mark.asyncio
async def test_a_valid_signed_url_works_for_a_jpeg_signature(
    client, storage, auth_doctor, anonymous
):
    """The service stores .jpg for JPEG uploads, so .png is not the whole keyspace.

    A key pattern or a fix that special-cased .png would leave half the keyspace
    either open or broken.
    """
    key, signed = await _upload_signature(
        client, auth_doctor, image=real_jpeg(), filename="signature.jpg"
    )
    assert key.endswith(".jpg")

    res = await anonymous.get(f"/{signed}")

    assert res.status_code == 200, res.text
    assert res.content == storage.read(key)
    assert res.headers["content-type"] == "image/jpeg"


# ---------------------------------------------------------------------------
# Revocation: the version is why a stateless signature can be withdrawn.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_uploading_a_signature_bumps_the_access_version(
    client, storage, db, auth_doctor
):
    """The revocation handle actually moves, and it is the upload that moves it."""

    doctor = auth_doctor["doctor"]
    before = doctor.signature_access_version

    await _upload_signature(client, auth_doctor)

    current = await db.scalar(
        select(Doctor.signature_access_version).where(Doctor.id == doctor.id)
    )
    assert current == before + 1


@pytest.mark.asyncio
async def test_replacing_a_signature_revokes_the_previous_url(
    client, storage, auth_doctor, anonymous
):
    """The point of the whole version scheme.

    The key is unchanged when the extension matches — doctor_N.png is overwritten
    in place — so without the version an old URL would not merely keep working,
    it would start serving the REPLACEMENT image.
    """
    _, first = await _upload_signature(client, auth_doctor)

    before = await anonymous.get(f"/{first}")
    assert before.status_code == 200, before.text

    _, second = await _upload_signature(client, auth_doctor)
    assert first != second

    stale = await anonymous.get(f"/{first}")
    assert stale.status_code == 403, (
        f"a URL minted before the replacement still served "
        f"{len(stale.content)} bytes"
    )


@pytest.mark.asyncio
async def test_a_url_minted_after_the_increment_works(
    client, storage, auth_doctor, anonymous
):
    """Revocation must not be a one-way door: the new URL has to work."""

    await _upload_signature(client, auth_doctor)
    key, second = await _upload_signature(client, auth_doctor)

    res = await anonymous.get(f"/{second}")

    assert res.status_code == 200, res.text
    assert res.content == storage.read(key)


@pytest.mark.asyncio
async def test_a_url_signed_at_a_superseded_version_is_refused(on_disk, anonymous):
    """A GENUINE signature over a stale version, so only the database can refuse it.

    Distinct from editing `v` in a URL, which the MAC catches. This one has a
    valid MAC and a valid expiry, and the only thing standing between it and the
    bytes is the comparison against signature_access_version. Delete that
    comparison and this test fails while every MAC test still passes.

    Version 0 is also deliberate: it is falsy, so a verifier written with
    `if not version` instead of `is None` would treat this as unsigned and take a
    different path.
    """
    stale = sign_key(on_disk["key"], access_version=on_disk["version"] - 1)

    res = await anonymous.get(f"/{stale}")

    assert res.status_code == 403
    assert res.content != on_disk["image"]


# ---------------------------------------------------------------------------
# Refused: no signature, wrong key, tampered field, expired.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anonymous_caller_cannot_download_a_doctors_signature(
    on_disk, anonymous
):
    """The vulnerability itself: the bare key used to return 200 and the bytes."""

    res = await anonymous.get(f"/{on_disk['key']}")

    assert res.status_code == 403, (
        f"anonymous caller received {res.status_code} for {on_disk['key']} "
        f"({len(res.content)} bytes)"
    )
    assert res.content != on_disk["image"]
    assert b"\x89PNG" not in res.content


@pytest.mark.asyncio
@pytest.mark.parametrize("doctor_id", [1, 2, 3, 17, 240])
async def test_signature_keys_cannot_be_enumerated_anonymously(
    storage, anonymous, doctor_id
):
    """Walking the id space must not distinguish a real signature from a gap.

    Written against storage directly rather than the upload route because the
    point is the id sweep: several ids exist on disk at once. Pre-fix every one
    of these returned the image.
    """
    key = f"media/signatures/doctor_{doctor_id}.png"
    storage.write(key, real_png())

    res = await anonymous.get(f"/{key}")

    assert res.status_code == 403
    assert b"\x89PNG" not in res.content


@pytest.mark.asyncio
async def test_one_doctors_valid_url_cannot_read_another_doctors_signature(
    client, storage, auth_doctor, auth_another_doctor, anonymous
):
    """The test that makes binding the KEY into the MAC worth having.

    Both doctors are real, both have uploaded, so both sit at the SAME current
    access version — which means the version check cannot be what refuses this.
    The only thing standing in the way is the key inside the MAC. Without it,
    holding your own signed URL would hand you every other doctor's signature.
    """
    _, mine = await _upload_signature(client, auth_doctor)
    theirs_key, _ = await _upload_signature(client, auth_another_doctor)

    res = await anonymous.get(f"/{theirs_key}", params=_params(mine))

    assert res.status_code == 403
    assert res.content != storage.read(theirs_key)


@pytest.mark.asyncio
async def test_a_tampered_signature_is_refused(on_disk, anonymous):
    """Flip one character of the MAC."""

    params = _params(sign_key(on_disk["key"], access_version=on_disk["version"]))
    original = params[SIGNATURE_PARAM]
    params[SIGNATURE_PARAM] = ("B" if original[0] != "B" else "C") + original[1:]

    res = await anonymous.get(f"/{on_disk['key']}", params=params)

    assert res.status_code == 403
    assert res.content != on_disk["image"]


@pytest.mark.asyncio
async def test_the_expiry_cannot_be_extended_without_resigning(on_disk, anonymous):
    """`exp` is inside the MAC, so pushing the deadline out breaks it.

    Without this the TTL would be advisory — a holder of any signed URL could
    turn it into a permanent one by editing a number.
    """
    params = _params(sign_key(on_disk["key"], access_version=on_disk["version"]))
    params[EXPIRY_PARAM] = str(int(params[EXPIRY_PARAM]) + 10 * 365 * 24 * 3600)

    res = await anonymous.get(f"/{on_disk['key']}", params=params)

    assert res.status_code == 403
    assert res.content != on_disk["image"]


@pytest.mark.asyncio
async def test_the_version_cannot_be_edited_without_resigning(on_disk, anonymous):
    """`v` is inside the MAC too.

    Otherwise revocation would be trivially defeated: hold a stale URL, type the
    next integer, and the version check waves it through.
    """
    params = _params(sign_key(on_disk["key"], access_version=on_disk["version"]))
    params[VERSION_PARAM] = str(int(params[VERSION_PARAM]) + 1)

    res = await anonymous.get(f"/{on_disk['key']}", params=params)

    assert res.status_code == 403
    assert res.content != on_disk["image"]


@pytest.mark.asyncio
async def test_an_expired_signed_url_is_refused(on_disk, anonymous):
    """A genuine MAC at the current version, over an elapsed deadline.

    Signed with a negative TTL rather than by freezing the clock, so the MAC is
    real and the ONLY reason to refuse is the expiry.
    """
    expired = sign_key(
        on_disk["key"], access_version=on_disk["version"], ttl_seconds=-60
    )

    res = await anonymous.get(f"/{expired}")

    assert res.status_code == 403
    assert b"\x89PNG" not in res.content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {},
        {EXPIRY_PARAM: "1"},
        {SIGNATURE_PARAM: "abc"},
        {VERSION_PARAM: "1"},
        {EXPIRY_PARAM: "1", VERSION_PARAM: "1"},
        {EXPIRY_PARAM: "", VERSION_PARAM: "", SIGNATURE_PARAM: ""},
        {EXPIRY_PARAM: "not-a-number", VERSION_PARAM: "1", SIGNATURE_PARAM: "a"},
        {EXPIRY_PARAM: "1e99", VERSION_PARAM: "1", SIGNATURE_PARAM: "a"},
        {EXPIRY_PARAM: "9" * 40, VERSION_PARAM: "1", SIGNATURE_PARAM: "a"},
        {EXPIRY_PARAM: "-1", VERSION_PARAM: "-1", SIGNATURE_PARAM: "a"},
        {EXPIRY_PARAM: "1", VERSION_PARAM: "not-a-number", SIGNATURE_PARAM: "a"},
        {EXPIRY_PARAM: "1", VERSION_PARAM: "9" * 40, SIGNATURE_PARAM: "a"},
    ],
)
async def test_malformed_signature_parameters_are_refused_not_crashed(
    on_disk, anonymous, params
):
    """These arrive on an unauthenticated query string, so verification is total.

    A 500 here would be an availability bug reachable by anyone, and the
    traceback would confirm the key exists.
    """
    res = await anonymous.get(f"/{on_disk['key']}", params=params)

    assert res.status_code == 403
    assert res.content != on_disk["image"]


# ---------------------------------------------------------------------------
# Guards: behaviour that must survive unchanged.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credential_documents_remain_unreachable(client, storage):
    """BMDC certificates and licences stay behind the authenticated route.

    Also covered in tests/api/test_file_serving.py; repeated here because the
    signature work edits exactly the prefix tuples that keep this closed.
    """
    key = "uploads/doctor_documents/doctor1_bmdc_secret.pdf"
    storage.write(key, PDF)

    res = await client.get(f"/{key}")

    assert res.status_code == 404, res.text
    assert b"%PDF" not in res.content


@pytest.mark.asyncio
async def test_credential_documents_are_not_reachable_by_signing_their_key(
    client, storage
):
    """A signature must not be a universal key to the storage bucket.

    uploads/ takes no signature parameters at all, so even a genuine MAC over a
    credential document's key buys nothing.
    """
    key = "uploads/doctor_documents/doctor1_bmdc_secret.pdf"
    storage.write(key, PDF)

    res = await client.get(f"/{sign_key(key, access_version=1)}")

    assert res.status_code == 404, res.text
    assert b"%PDF" not in res.content


# Percent-encoded, and that matters. httpx resolves a literal "../.." in the
# path before the request is built, so a test written that way never reaches the
# application at all — it 404s on a route that does not match, and would keep
# passing with every server-side guard deleted. "%2e%2e" survives the client and
# Starlette decodes it back into a real traversal key, which is the vector an
# attacker actually has.
TRAVERSAL_PATH = "/media/signatures/%2e%2e/%2e%2e/outside_the_root.txt"
TRAVERSAL_KEY = "media/signatures/../../outside_the_root.txt"


@pytest.mark.asyncio
async def test_path_traversal_remains_refused(client, storage, tmp_path):
    """A key escaping the storage root is refused, never served."""

    (tmp_path.parent / "outside_the_root.txt").write_bytes(b"root:x:0:0:")

    res = await client.get(TRAVERSAL_PATH)

    assert res.status_code == 403
    assert b"root:" not in res.content


@pytest.mark.asyncio
async def test_a_literal_dotdot_never_even_reaches_the_route(client, storage):
    """Documents why the tests above are percent-encoded.

    Not a security assertion — a note in executable form, so nobody "simplifies"
    TRAVERSAL_PATH back to a literal ../.. and quietly stops testing the server.
    """
    res = await client.get("/media/signatures/../../outside_the_root.txt")

    assert res.status_code == 404


@pytest.mark.asyncio
async def test_a_validly_signed_traversal_key_is_still_refused(
    client, storage, tmp_path
):
    """A signature proves a URL came from us, never that it may leave the root.

    Refused by the strict key pattern before storage is touched, so the day
    something signs a key built from user input the MAC does not become the
    exploit. The storage root guard behind it is covered in test_storage.py.
    """
    (tmp_path.parent / "outside_the_root.txt").write_bytes(b"root:x:0:0:")

    signed = sign_key(TRAVERSAL_KEY, access_version=1)

    res = await client.get(TRAVERSAL_PATH, params=_params(signed))

    assert res.status_code == 403
    assert b"root:" not in res.content


@pytest.mark.asyncio
async def test_a_validly_signed_key_for_no_such_doctor_is_refused(client, storage):
    """Fail closed when the key parses but the doctor is gone."""

    key = "media/signatures/doctor_999999.png"
    storage.write(key, real_png())

    res = await client.get(f"/{sign_key(key, access_version=1)}")

    assert res.status_code == 403
    assert b"\x89PNG" not in res.content


@pytest.mark.asyncio
async def test_unknown_media_prefix_remains_refused(client, storage):
    """Only the listed prefixes are served, whatever else exists on disk."""

    storage.write("media/private/secret.png", real_png())

    res = await client.get("/media/private/secret.png")

    assert res.status_code == 404


@pytest.mark.asyncio
async def test_clinic_logo_stays_publicly_served(client, storage):
    """A logo is public branding, rendered for anonymous visitors.

    The signature work must not sweep clinic logos up with signatures:
    clinic_logo_service writes here and the frontend builds
    `${apiUrl}${logo_url}` with no credentials to offer.
    """
    logo = real_png()
    storage.write("uploads/clinic_logos/abc.png", logo)

    res = await client.get("/uploads/clinic_logos/abc.png")

    assert res.status_code == 200, res.text
    assert res.content == logo


@pytest.mark.asyncio
async def test_clinic_logo_keeps_its_hardening_headers(client, storage):
    """User-uploaded bytes must stay unsniffable on the path that stays public."""

    storage.write("uploads/clinic_logos/def.png", real_png())

    res = await client.get("/uploads/clinic_logos/def.png")

    assert res.headers.get("x-content-type-options") == "nosniff"
    assert res.headers["content-type"] == "image/png"

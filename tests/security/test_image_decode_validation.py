"""A valid magic header is not a valid image.

Eight correct PNG bytes followed by garbage passed the old check, then blew up
much later when reportlab asked Pillow to render it into a prescription PDF.
"""

import io

import pytest
from PIL import Image

from app.security.file_validation import (
    ensure_decodable_image,
    ensure_document,
    ensure_image,
)

IMAGE_TYPES = {"image/png", "image/jpeg"}
DOC_TYPES = {"application/pdf", "image/png", "image/jpeg"}


def real_png(size=(40, 20)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def real_jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), (200, 10, 10)).save(buf, format="JPEG")
    return buf.getvalue()


def real_jpeg_large() -> bytes:
    """Big enough that a truncation actually removes scan data."""

    buf = io.BytesIO()
    Image.new("RGB", (800, 600), (200, 60, 40)).save(buf, format="JPEG")
    return buf.getvalue()


# The exact shape of the file that broke PDF generation.
HEADER_ONLY_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 400


def test_real_png_passes():
    assert ensure_image(real_png(), IMAGE_TYPES) == "image/png"


def test_real_jpeg_passes():
    assert ensure_image(real_jpeg(), IMAGE_TYPES) == "image/jpeg"


def test_png_header_followed_by_garbage_is_rejected():
    """The regression: valid magic bytes, undecodable pixels."""

    with pytest.raises(ValueError, match="not a readable image"):
        ensure_image(HEADER_ONLY_PNG, IMAGE_TYPES)


def test_truncated_png_is_rejected():
    """Header and structure look fine; the pixel data is cut short."""

    full = real_png(size=(300, 300))
    with pytest.raises(ValueError):
        ensure_image(full[: len(full) // 2], IMAGE_TYPES)


@pytest.mark.parametrize("keep", [0.9, 0.6, 0.3])
def test_truncated_jpeg_is_rejected(keep):
    """The case that needs the second decode pass.

    JPEG has no per-chunk checksums, so a truncated one sails through
    Image.verify(); only a full load() notices the scan data is missing.
    Signatures accept JPEG, so this is a real upload path, not a hypothetical.
    """

    full = real_jpeg_large()
    with pytest.raises(ValueError, match="not a readable image"):
        ensure_image(full[: int(len(full) * keep)], IMAGE_TYPES)


def test_verify_alone_would_miss_a_truncated_jpeg():
    """Pins *why* ensure_decodable_image does two passes.

    If Pillow ever makes verify() catch this, the second pass becomes
    redundant and this test should fail loudly to say so.
    """

    truncated = real_jpeg_large()[:3000]

    img = Image.open(io.BytesIO(truncated))
    img.verify()  # passes — no exception

    with pytest.raises(OSError):
        Image.open(io.BytesIO(truncated)).load()


def test_non_image_bytes_still_rejected_by_magic():
    with pytest.raises(ValueError, match="not a valid image"):
        ensure_image(b"this is plainly not an image", IMAGE_TYPES)


def test_ensure_decodable_accepts_a_real_image():
    ensure_decodable_image(real_png())


def test_document_pdf_skips_image_decoding():
    """Pillow cannot open a PDF — it must not be run through the decoder."""

    pdf = b"%PDF-1.4\n% minimal\ntrailer\n%%EOF\n"
    assert ensure_document(pdf, DOC_TYPES) == "application/pdf"


def test_document_image_is_decode_checked():
    with pytest.raises(ValueError, match="not a readable image"):
        ensure_document(HEADER_ONLY_PNG, DOC_TYPES)


def test_document_real_image_passes():
    assert ensure_document(real_png(), DOC_TYPES) == "image/png"

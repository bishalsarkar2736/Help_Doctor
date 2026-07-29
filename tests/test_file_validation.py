import io

import pytest
from PIL import Image

from app.security.file_validation import sniff_image_type, ensure_image

# Header-only stubs. These are enough for sniff_image_type, which inspects
# magic bytes and nothing else — but they are NOT decodable images, so they
# must not be used with ensure_image (see test_ensure_image_rejects_header_only).
PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG_HEADER = b"\xff\xd8\xff\xe0" + b"\x00" * 16
WEBP_HEADER = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 16


def _encode(fmt: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 16), (90, 120, 150)).save(buf, format=fmt)
    return buf.getvalue()


REAL_PNG = _encode("PNG")
REAL_WEBP = _encode("WEBP")


def test_sniff_detects_real_images():
    assert sniff_image_type(PNG_HEADER) == "image/png"
    assert sniff_image_type(JPEG_HEADER) == "image/jpeg"
    assert sniff_image_type(WEBP_HEADER) == "image/webp"


def test_sniff_rejects_non_images():
    assert sniff_image_type(b"<?php system($_GET[0]); ?>") is None
    assert sniff_image_type(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None
    assert sniff_image_type(b"") is None


def test_ensure_image_accepts_allowed():
    assert ensure_image(REAL_PNG, {"image/png", "image/jpeg"}) == "image/png"


def test_ensure_image_rejects_valid_image_of_disallowed_type():
    # A genuinely decodable WEBP — rejected on type, not on decodability.
    with pytest.raises(ValueError, match="not a valid image"):
        ensure_image(REAL_WEBP, {"image/png", "image/jpeg"})


def test_ensure_image_rejects_spoofed_content():
    # Bytes are not an image, regardless of any claimed Content-Type.
    with pytest.raises(ValueError):
        ensure_image(b"not really a png", {"image/png"})


def test_ensure_image_rejects_header_only():
    """Correct magic bytes are not sufficient — the pixels must decode."""

    with pytest.raises(ValueError, match="not a readable image"):
        ensure_image(PNG_HEADER, {"image/png"})

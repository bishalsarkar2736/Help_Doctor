import pytest

from app.security.file_validation import sniff_image_type, ensure_image

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 16


def test_sniff_detects_real_images():
    assert sniff_image_type(PNG) == "image/png"
    assert sniff_image_type(JPEG) == "image/jpeg"
    assert sniff_image_type(WEBP) == "image/webp"


def test_sniff_rejects_non_images():
    assert sniff_image_type(b"<?php system($_GET[0]); ?>") is None
    assert sniff_image_type(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None
    assert sniff_image_type(b"") is None


def test_ensure_image_accepts_allowed():
    assert ensure_image(PNG, {"image/png", "image/jpeg"}) == "image/png"


def test_ensure_image_rejects_valid_image_of_disallowed_type():
    # A real WEBP, but WEBP isn't allowed for (e.g.) signatures.
    with pytest.raises(ValueError):
        ensure_image(WEBP, {"image/png", "image/jpeg"})


def test_ensure_image_rejects_spoofed_content():
    # Bytes are not an image, regardless of any claimed Content-Type.
    with pytest.raises(ValueError):
        ensure_image(b"not really a png", {"image/png"})

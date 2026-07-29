"""Content-based (magic-byte) file type detection.

The client-supplied ``Content-Type`` header is attacker-controlled and must
never be trusted for security decisions. These helpers sniff the actual bytes so
an upload can be verified to really be the image type it claims.

Magic bytes alone are not enough for images. An eight-byte PNG header followed
by garbage passes a header check but explodes later, when reportlab asks Pillow
to render it into a prescription PDF — turning a bad upload into a 500 on a
clinical path, far away from the request that caused it. So images are also
decoded here, at the point of upload, where the error is actionable.
"""

import io

from PIL import Image, UnidentifiedImageError


def sniff_image_type(content: bytes) -> str | None:
    """Return the image MIME type from magic bytes, or None if not an image."""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    # WEBP: "RIFF" .... "WEBP"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def sniff_document_type(content: bytes) -> str | None:
    """Detect a credential document: PDF, or any supported image."""
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    return sniff_image_type(content)


def ensure_document(content: bytes, allowed: set[str]) -> str:
    """Verify uploaded bytes are a real PDF/image of an allowed type."""
    detected = sniff_document_type(content)
    if detected is None or detected not in allowed:
        raise ValueError("File content is not a valid PDF or image")

    # Only images get decoded — Pillow cannot open a PDF, and a credential
    # image that will not render is useless to the reviewing admin.
    if detected != "application/pdf":
        ensure_decodable_image(content)

    return detected


def ensure_decodable_image(content: bytes) -> None:
    """Prove the pixels actually parse, not just that the header looks right.

    Raises ValueError if the image is corrupt, truncated, or a decompression
    bomb.

    Both passes are needed, and which one fires depends on the format:

    * PNG stores per-chunk CRCs, so ``verify()`` catches truncation on its own.
    * JPEG has no such checksums — a truncated JPEG passes ``verify()`` cleanly
      and only fails when the scan data is actually decoded. ``verify()`` also
      consumes the object, hence the reopen.

    Signatures accept JPEG, so dropping the ``load()`` pass would let a
    truncated JPEG through to the PDF renderer.
    """

    try:
        with Image.open(io.BytesIO(content)) as img:
            img.verify()

        with Image.open(io.BytesIO(content)) as img:
            img.load()

    except Image.DecompressionBombError:
        # Pillow's pixel-count guard: a small file that expands enormously.
        raise ValueError("Image dimensions are too large")

    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise ValueError("File is not a readable image")


def ensure_image(content: bytes, allowed: set[str]) -> str:
    """Verify uploaded bytes are a readable image of an allowed type.

    Raises ValueError with a caller-friendly message otherwise.
    """
    detected = sniff_image_type(content)
    if detected is None or detected not in allowed:
        raise ValueError("File content is not a valid image")

    ensure_decodable_image(content)
    return detected

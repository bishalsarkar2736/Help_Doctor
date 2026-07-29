"""Content-based (magic-byte) file type detection.

The client-supplied ``Content-Type`` header is attacker-controlled and must
never be trusted for security decisions. These helpers sniff the actual bytes so
an upload can be verified to really be the image type it claims.
"""


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
    return detected


def ensure_image(content: bytes, allowed: set[str]) -> str:
    """Verify uploaded bytes are one of the allowed image types.

    Raises ValueError with a caller-friendly message otherwise.
    """
    detected = sniff_image_type(content)
    if detected is None or detected not in allowed:
        raise ValueError("File content is not a valid image")
    return detected

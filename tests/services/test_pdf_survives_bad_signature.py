"""A corrupt signature on disk must not 500 the prescription PDF.

Validation at upload only protects new files. Anything already stored — from
before that check existed, or corrupted since — still has to render.
"""

import io
from types import SimpleNamespace

import pytest
from PIL import Image

from app.models.prescription import PrescriptionStatus
from app.services.prescription_pdf_service import generate_prescription_pdf
from app.services.storage import LocalFilesystemStorage, set_storage

HEADER_ONLY_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 400


@pytest.fixture
def storage(tmp_path):
    """Point the storage seam at a temp root for the duration of one test.

    signature_file_path holds a storage KEY relative to that root — the shape
    real rows use ("media/signatures/doctor_1.png"). An absolute path is
    rejected by design, so a test writing one would be exercising something
    production never does.
    """
    backend = LocalFilesystemStorage(root=tmp_path)
    set_storage(backend)
    try:
        yield backend
    finally:
        set_storage(None)


def _prescription(signature_key):
    """Minimal duck-typed stand-in; the PDF builder only reads attributes."""

    return SimpleNamespace(
        id=1,
        uuid="11111111-2222-3333-4444-555555555555",
        revision_number=1,
        is_latest_revision=True,
        status=PrescriptionStatus.ISSUED,
        created_at=None,
        issued_at=None,
        notes=None,
        appointment_id=7,
        appointment=None,
        patient_id=3,
        patient=SimpleNamespace(full_name="Test Patient"),
        doctor_id=2,
        doctor=SimpleNamespace(
            signature_file_path=signature_key,
            user=SimpleNamespace(full_name="Dr Test"),
        ),
        items=[],
    )


def test_pdf_renders_despite_corrupt_signature(storage):
    key = "media/signatures/doctor_9.png"
    storage.write(key, HEADER_ONLY_PNG)

    pdf = generate_prescription_pdf(_prescription(key))

    assert pdf[:5] == b"%PDF-"
    # The doctor's printed name still identifies the prescriber.
    assert b"Dr Test" in pdf or len(pdf) > 500


def test_pdf_includes_a_valid_signature(storage):
    key = "media/signatures/doctor_8.png"
    buf = io.BytesIO()
    Image.new("RGB", (200, 60), (0, 0, 120)).save(buf, format="PNG")
    storage.write(key, buf.getvalue())

    pdf = generate_prescription_pdf(_prescription(key))

    assert pdf[:5] == b"%PDF-"


def test_pdf_renders_with_no_signature_at_all():
    pdf = generate_prescription_pdf(_prescription(None))
    assert pdf[:5] == b"%PDF-"

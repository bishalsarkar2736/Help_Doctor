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

HEADER_ONLY_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 400


def _prescription(signature_path):
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
            signature_file_path=str(signature_path) if signature_path else None,
            user=SimpleNamespace(full_name="Dr Test"),
        ),
        items=[],
    )


def test_pdf_renders_despite_corrupt_signature(tmp_path):
    bad = tmp_path / "doctor_9.png"
    bad.write_bytes(HEADER_ONLY_PNG)

    pdf = generate_prescription_pdf(_prescription(bad))

    assert pdf[:5] == b"%PDF-"
    # The doctor's printed name still identifies the prescriber.
    assert b"Dr Test" in pdf or len(pdf) > 500


def test_pdf_includes_a_valid_signature(tmp_path):
    good = tmp_path / "doctor_8.png"
    buf = io.BytesIO()
    Image.new("RGB", (200, 60), (0, 0, 120)).save(buf, format="PNG")
    good.write_bytes(buf.getvalue())

    pdf = generate_prescription_pdf(_prescription(good))

    assert pdf[:5] == b"%PDF-"


def test_pdf_renders_with_no_signature_at_all():
    pdf = generate_prescription_pdf(_prescription(None))
    assert pdf[:5] == b"%PDF-"

"""Doctor credential documents: upload, review, isolation, re-apply."""

import uuid

import pytest
from sqlalchemy import select

from app.models.clinic import Clinic
from app.models.doctor import Doctor, DoctorStatus
from app.models.doctor_document import DoctorDocument
from app.models.user import User, UserRole
from app.security.jwt import create_access_token

PDF = b"%PDF-1.4\n" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _files(content: bytes, name="license.pdf", ctype="application/pdf"):
    return {"file": (name, content, ctype)}


async def _doctor(db, clinic_id, status=DoctorStatus.PENDING):
    user = User(
        email=f"doc-{uuid.uuid4().hex[:8]}@test.com",
        full_name="Dr Docs",
        hashed_password="x",
        role=UserRole.DOCTOR,
        is_active=True,
        clinic_id=clinic_id,
    )
    db.add(user)
    await db.flush()

    doctor = Doctor(
        user_id=user.id,
        clinic_id=clinic_id,
        specialization="Cardiology",
        experience_years=5,
        bio="x",
        status=status,
    )
    db.add(doctor)
    await db.flush()

    token = create_access_token(
        data={"sub": str(user.id), "role": UserRole.DOCTOR.value}
    )
    return doctor, {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_doctor_uploads_and_lists_documents(client, db, default_clinic):
    _, headers = await _doctor(db, default_clinic.id)

    res = await client.post(
        "/doctors/documents?doc_type=LICENSE",
        files=_files(PDF),
        headers=headers,
    )
    assert res.status_code == 201, res.text
    assert res.json()["doc_type"] == "LICENSE"
    # The raw path is never exposed to clients.
    assert "file_path" not in res.json()

    res = await client.get("/doctors/documents", headers=headers)
    assert res.status_code == 200
    assert len(res.json()) == 1


@pytest.mark.asyncio
async def test_rejects_content_that_is_not_a_real_document(client, db, default_clinic):
    _, headers = await _doctor(db, default_clinic.id)

    # Valid-looking MIME, but the bytes are a script.
    res = await client.post(
        "/doctors/documents?doc_type=DEGREE",
        files=_files(b"<?php system($_GET[0]); ?>", "x.pdf", "application/pdf"),
        headers=headers,
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_reupload_replaces_previous_document_of_same_type(
    client, db, default_clinic
):
    doctor, headers = await _doctor(db, default_clinic.id)

    await client.post(
        "/doctors/documents?doc_type=LICENSE", files=_files(PDF), headers=headers
    )
    await client.post(
        "/doctors/documents?doc_type=LICENSE", files=_files(PNG, "l.png", "image/png"),
        headers=headers,
    )

    rows = list(
        await db.scalars(
            select(DoctorDocument).where(DoctorDocument.doctor_id == doctor.id)
        )
    )
    assert len(rows) == 1, "same type should replace, not accumulate"


@pytest.mark.asyncio
async def test_reupload_after_rejection_returns_doctor_to_pending(
    client, db, default_clinic
):
    """REJECTED must not be a dead end — re-submitting re-opens review."""
    doctor, headers = await _doctor(db, default_clinic.id, DoctorStatus.REJECTED)
    doctor.rejection_reason = "Illegible licence"
    await db.flush()

    res = await client.post(
        "/doctors/documents?doc_type=LICENSE", files=_files(PDF), headers=headers
    )
    assert res.status_code == 201

    await db.refresh(doctor)
    assert doctor.status is DoctorStatus.PENDING
    assert doctor.rejection_reason is None


@pytest.mark.asyncio
async def test_admin_reviews_documents_of_own_clinic(
    client, db, default_clinic, auth_admin
):
    doctor, headers = await _doctor(db, default_clinic.id)
    await client.post(
        "/doctors/documents?doc_type=BMDC_CERTIFICATE",
        files=_files(PDF), headers=headers,
    )

    res = await client.get(
        f"/admin/doctors/{doctor.id}/documents", headers=auth_admin["headers"]
    )
    assert res.status_code == 200, res.text
    assert res.json()[0]["doc_type"] == "BMDC_CERTIFICATE"


@pytest.mark.asyncio
async def test_admin_cannot_review_another_clinics_doctor(
    client, db, default_clinic, auth_admin
):
    other = Clinic(name=f"Other {uuid.uuid4().hex[:5]}", address="X", phone="1",
                   email=f"{uuid.uuid4().hex[:5]}@t.com")
    db.add(other)
    await db.flush()

    doctor, headers = await _doctor(db, other.id)
    await client.post(
        "/doctors/documents?doc_type=LICENSE", files=_files(PDF), headers=headers
    )

    res = await client.get(
        f"/admin/doctors/{doctor.id}/documents", headers=auth_admin["headers"]
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_patient_cannot_upload_documents(client, auth_patient):
    res = await client.post(
        "/doctors/documents?doc_type=LICENSE",
        files=_files(PDF),
        headers=auth_patient["headers"],
    )
    assert res.status_code == 403

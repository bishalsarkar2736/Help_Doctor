import uuid
import pytest

from app.models.user import User, UserRole
from app.models.doctor import Doctor, DoctorStatus
from app.models.clinic import Clinic, ClinicStatus


async def _make_doctor(db, clinic_id, *, name, specialization, status=DoctorStatus.APPROVED):
    user = User(
        email=f"doc-{uuid.uuid4()}@test.com",
        full_name=name,
        hashed_password="x",
        role=UserRole.DOCTOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    doctor = Doctor(
        user_id=user.id,
        specialization=specialization,
        experience_years=5,
        bio="Test",
        clinic_id=clinic_id,
        status=status,
    )
    db.add(doctor)
    await db.flush()
    await db.refresh(doctor)
    return doctor


# ----------------------------- A: list + filters -----------------------------

@pytest.mark.asyncio
async def test_list_includes_clinic_fields(client, db, default_clinic):
    await _make_doctor(db, default_clinic.id, name="Dr Alice", specialization="Cardiology")

    res = await client.get("/doctors")
    assert res.status_code == 200
    row = next(d for d in res.json() if d["name"] == "Dr Alice")
    assert row["clinic_id"] == default_clinic.id
    assert row["clinic_name"] == default_clinic.name


@pytest.mark.asyncio
async def test_search_by_name(client, db, default_clinic):
    await _make_doctor(db, default_clinic.id, name="Dr House", specialization="Diagnostics")
    await _make_doctor(db, default_clinic.id, name="Dr Grey", specialization="Surgery")

    res = await client.get("/doctors", params={"q": "house"})
    names = [d["name"] for d in res.json()]
    assert names == ["Dr House"]


@pytest.mark.asyncio
async def test_filter_by_specialization(client, db, default_clinic):
    await _make_doctor(db, default_clinic.id, name="Dr A", specialization="Neurology")
    await _make_doctor(db, default_clinic.id, name="Dr B", specialization="Cardiology")

    res = await client.get("/doctors", params={"specialization": "neurology"})
    body = res.json()
    assert all(d["specialization"] == "Neurology" for d in body)
    assert any(d["name"] == "Dr A" for d in body)


@pytest.mark.asyncio
async def test_filter_by_clinic(client, db, default_clinic):
    other = Clinic(name="Other Clinic", status=ClinicStatus.ACTIVE)
    db.add(other)
    await db.flush()

    await _make_doctor(db, default_clinic.id, name="Dr Here", specialization="X")
    await _make_doctor(db, other.id, name="Dr There", specialization="Y")

    res = await client.get("/doctors", params={"clinic_id": other.id})
    names = [d["name"] for d in res.json()]
    assert names == ["Dr There"]


@pytest.mark.asyncio
async def test_pending_doctor_excluded_from_list(client, db, default_clinic):
    await _make_doctor(
        db, default_clinic.id, name="Dr Pending", specialization="Z",
        status=DoctorStatus.PENDING,
    )
    res = await client.get("/doctors")
    assert all(d["name"] != "Dr Pending" for d in res.json())


# ----------------------------- B: detail -----------------------------

@pytest.mark.asyncio
async def test_doctor_detail(client, db, default_clinic):
    doc = await _make_doctor(db, default_clinic.id, name="Dr Detail", specialization="ENT")

    res = await client.get(f"/doctors/{doc.id}")
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Dr Detail"
    assert body["clinic_name"] == default_clinic.name
    assert body["specialization"] == "ENT"


@pytest.mark.asyncio
async def test_detail_404_for_pending_or_missing(client, db, default_clinic):
    pending = await _make_doctor(
        db, default_clinic.id, name="Dr Hidden", specialization="ENT",
        status=DoctorStatus.PENDING,
    )
    assert (await client.get(f"/doctors/{pending.id}")).status_code == 404
    assert (await client.get("/doctors/99999")).status_code == 404


# ----------------------------- C: specializations -----------------------------

@pytest.mark.asyncio
async def test_specializations_distinct(client, db, default_clinic):
    await _make_doctor(db, default_clinic.id, name="D1", specialization="Cardiology")
    await _make_doctor(db, default_clinic.id, name="D2", specialization="Cardiology")
    await _make_doctor(db, default_clinic.id, name="D3", specialization="Neurology")

    res = await client.get("/doctors/specializations")
    assert res.status_code == 200
    specs = res.json()
    assert specs.count("Cardiology") == 1
    assert "Neurology" in specs


# ----------------------------- D: public clinics -----------------------------

@pytest.mark.asyncio
async def test_public_clinics_active_only(client, db, default_clinic):
    suspended = Clinic(name="Suspended Clinic", status=ClinicStatus.SUSPENDED)
    db.add(suspended)
    await db.flush()

    res = await client.get("/clinics")
    assert res.status_code == 200
    names = [c["name"] for c in res.json()]
    assert default_clinic.name in names
    assert "Suspended Clinic" not in names
    # response is minimal
    assert set(res.json()[0].keys()) == {"id", "name"}

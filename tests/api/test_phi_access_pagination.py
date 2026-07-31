"""Pagination of the PHI access log, and auditing reads of it.

A truncated audit list is worse than no list: a reviewer who sees 100 rows and
assumes that is everything will draw the wrong conclusion. So total_count and
has_next are asserted directly, not just the page contents.
"""

import pytest
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.phi_access_log import PHIAccessLog, PHIAction, PHIResourceType


async def _seed_accesses(db, actor_id, clinic_id, patient_id, count):
    db.add_all(
        [
            PHIAccessLog(
                actor_user_id=actor_id,
                actor_role="doctor",
                clinic_id=clinic_id,
                patient_id=patient_id,
                resource_type=PHIResourceType.PATIENT_PROFILE,
                resource_id=i,
                action=PHIAction.VIEW,
                request_id=f"req-{i}",
            )
            for i in range(count)
        ]
    )
    await db.commit()


@pytest.mark.asyncio
async def test_pagination_reports_total_and_has_next(
    client, db, auth_admin, auth_doctor, patient_user, default_clinic
):
    await _seed_accesses(
        db,
        auth_doctor["user"].id,
        default_clinic.id,
        patient_user.id,
        count=25,
    )

    res = await client.get(
        "/admin/phi-access",
        params={"clinic_id": default_clinic.id, "limit": 10, "offset": 0},
        headers=auth_admin["headers"],
    )
    assert res.status_code == 200, res.text

    body = res.json()
    assert len(body["items"]) == 10
    assert body["total_count"] >= 25
    assert body["limit"] == 10
    assert body["offset"] == 0
    assert body["has_next"] is True


@pytest.mark.asyncio
async def test_last_page_reports_has_next_false(
    client, db, auth_admin, auth_doctor, patient_user, default_clinic
):
    await _seed_accesses(
        db, auth_doctor["user"].id, default_clinic.id, patient_user.id, count=12
    )

    total = (
        await client.get(
            "/admin/phi-access",
            params={"clinic_id": default_clinic.id, "limit": 1},
            headers=auth_admin["headers"],
        )
    ).json()["total_count"]

    res = await client.get(
        "/admin/phi-access",
        params={
            "clinic_id": default_clinic.id,
            "limit": 100,
            "offset": max(total - 2, 0),
        },
        headers=auth_admin["headers"],
    )
    assert res.status_code == 200
    assert res.json()["has_next"] is False


@pytest.mark.asyncio
async def test_total_count_reflects_the_filters_not_the_whole_table(
    client, db, auth_admin, auth_doctor, patient_user, default_clinic
):
    """Counting before filtering would tell a reviewer the wrong story."""

    await _seed_accesses(
        db, auth_doctor["user"].id, default_clinic.id, patient_user.id, count=5
    )

    unfiltered = (
        await client.get(
            "/admin/phi-access",
            params={"clinic_id": default_clinic.id, "limit": 1},
            headers=auth_admin["headers"],
        )
    ).json()["total_count"]

    filtered = (
        await client.get(
            "/admin/phi-access",
            params={
                "clinic_id": default_clinic.id,
                "limit": 1,
                "resource_type": "a_type_that_does_not_exist",
            },
            headers=auth_admin["headers"],
        )
    ).json()["total_count"]

    assert unfiltered >= 5
    assert filtered == 0


@pytest.mark.asyncio
async def test_offset_walks_without_repeating_rows(
    client, db, auth_admin, auth_doctor, patient_user, default_clinic
):
    await _seed_accesses(
        db, auth_doctor["user"].id, default_clinic.id, patient_user.id, count=15
    )

    page1 = (
        await client.get(
            "/admin/phi-access",
            params={"clinic_id": default_clinic.id, "limit": 5, "offset": 0},
            headers=auth_admin["headers"],
        )
    ).json()["items"]

    page2 = (
        await client.get(
            "/admin/phi-access",
            params={"clinic_id": default_clinic.id, "limit": 5, "offset": 5},
            headers=auth_admin["headers"],
        )
    ).json()["items"]

    ids1 = {r["id"] for r in page1}
    ids2 = {r["id"] for r in page2}
    assert len(ids1) == 5 and len(ids2) == 5
    assert ids1.isdisjoint(ids2), "pages overlap — the ordering is not stable"


@pytest.mark.asyncio
async def test_reading_the_access_log_is_itself_audited(
    client, db, auth_admin, auth_doctor, patient_user, default_clinic
):
    """An audit trail an admin can mine without leaving a trace is not one."""

    await _seed_accesses(
        db, auth_doctor["user"].id, default_clinic.id, patient_user.id, count=3
    )

    res = await client.get(
        "/admin/phi-access",
        params={
            "clinic_id": default_clinic.id,
            "patient_id": patient_user.id,
        },
        headers=auth_admin["headers"],
    )
    assert res.status_code == 200

    entry = await db.scalar(
        select(AuditLog)
        .where(
            AuditLog.event_type == "phi_access_log",
            AuditLog.action == "query",
        )
        .order_by(AuditLog.id.desc())
    )
    assert entry is not None, "reading the access log left no trace"
    assert entry.user_id == auth_admin["user"].id

    # The details must say WHAT was examined, so a later review can
    # reconstruct exactly what this administrator went looking for.
    assert entry.details["patient_id"] == patient_user.id
    assert entry.details["clinic_id"] == default_clinic.id


@pytest.mark.asyncio
async def test_the_meta_audit_does_not_pollute_the_phi_log(
    client, db, auth_admin, auth_doctor, patient_user, default_clinic
):
    """Querying the log must not append to the log it is querying."""

    await _seed_accesses(
        db, auth_doctor["user"].id, default_clinic.id, patient_user.id, count=2
    )

    before = await db.scalar(
        select(PHIAccessLog.id)
        .where(PHIAccessLog.clinic_id == default_clinic.id)
        .order_by(PHIAccessLog.id.desc())
        .limit(1)
    )

    await client.get(
        "/admin/phi-access",
        params={"clinic_id": default_clinic.id},
        headers=auth_admin["headers"],
    )

    after = await db.scalar(
        select(PHIAccessLog.id)
        .where(PHIAccessLog.clinic_id == default_clinic.id)
        .order_by(PHIAccessLog.id.desc())
        .limit(1)
    )
    assert after == before, (
        "the reviewer's own query was written into phi_access_logs, which "
        "would let routine review bury the accesses being reviewed"
    )


@pytest.mark.asyncio
async def test_limit_is_capped(client, auth_admin, default_clinic):
    """An unbounded limit would let one request pull the whole table."""

    res = await client.get(
        "/admin/phi-access",
        params={"clinic_id": default_clinic.id, "limit": 100_000},
        headers=auth_admin["headers"],
    )
    assert res.status_code == 422

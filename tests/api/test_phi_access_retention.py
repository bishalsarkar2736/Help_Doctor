"""Retention purge for phi_access_logs.

The dangerous failure here is not "the purge did not run" — it is "the purge
deleted evidence it should have kept". So every test that asserts something was
deleted is paired with one asserting the in-window rows survived.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models.phi_access_log import PHIAccessLog, PHIAction, PHIResourceType
from app.services.phi_access_retention_service import (
    count_expired_phi_access_logs,
    purge_expired_phi_access_logs,
)

RETENTION_DAYS = 2190  # six years, the configured default


async def _seed(db, actor_id, clinic_id, patient_id, *, age_days, count=1):
    created = datetime.now(timezone.utc) - timedelta(days=age_days)
    rows = [
        PHIAccessLog(
            actor_user_id=actor_id,
            actor_role="doctor",
            clinic_id=clinic_id,
            patient_id=patient_id,
            resource_type=PHIResourceType.PATIENT_PROFILE,
            action=PHIAction.VIEW,
            created_at=created,
        )
        for _ in range(count)
    ]
    db.add_all(rows)
    await db.commit()
    return rows


async def _total(db):
    return await db.scalar(select(func.count()).select_from(PHIAccessLog))


@pytest.mark.asyncio
async def test_purges_rows_past_the_window(
    db, auth_doctor, patient_user, default_clinic
):
    await _seed(
        db,
        auth_doctor["user"].id,
        default_clinic.id,
        patient_user.id,
        age_days=RETENTION_DAYS + 30,
        count=5,
    )

    deleted = await purge_expired_phi_access_logs(
        db=db, retention_days=RETENTION_DAYS, batch_size=100, max_batches=10
    )

    assert deleted == 5
    assert await count_expired_phi_access_logs(
        db=db, retention_days=RETENTION_DAYS
    ) == 0


@pytest.mark.asyncio
async def test_never_deletes_rows_inside_the_window(
    db, auth_doctor, patient_user, default_clinic
):
    """The one that matters: retained evidence must survive the purge."""

    await _seed(
        db,
        auth_doctor["user"].id,
        default_clinic.id,
        patient_user.id,
        age_days=RETENTION_DAYS - 30,
        count=4,
    )
    before = await _total(db)

    deleted = await purge_expired_phi_access_logs(
        db=db, retention_days=RETENTION_DAYS, batch_size=100, max_batches=10
    )

    assert deleted == 0
    assert await _total(db) == before


@pytest.mark.asyncio
async def test_a_row_one_day_inside_the_boundary_is_kept(
    db, auth_doctor, patient_user, default_clinic
):
    """Off-by-one at the cutoff would quietly delete a year's worth early."""

    kept = await _seed(
        db,
        auth_doctor["user"].id,
        default_clinic.id,
        patient_user.id,
        age_days=RETENTION_DAYS - 1,
    )
    expired = await _seed(
        db,
        auth_doctor["user"].id,
        default_clinic.id,
        patient_user.id,
        age_days=RETENTION_DAYS + 1,
    )
    kept_id, expired_id = kept[0].id, expired[0].id

    await purge_expired_phi_access_logs(
        db=db, retention_days=RETENTION_DAYS, batch_size=100, max_batches=10
    )

    assert await db.get(PHIAccessLog, kept_id) is not None
    assert await db.get(PHIAccessLog, expired_id) is None


@pytest.mark.asyncio
async def test_batching_drains_across_multiple_batches(
    db, auth_doctor, patient_user, default_clinic
):
    await _seed(
        db,
        auth_doctor["user"].id,
        default_clinic.id,
        patient_user.id,
        age_days=RETENTION_DAYS + 10,
        count=25,
    )

    deleted = await purge_expired_phi_access_logs(
        db=db, retention_days=RETENTION_DAYS, batch_size=10, max_batches=10
    )

    assert deleted == 25


@pytest.mark.asyncio
async def test_max_batches_bounds_a_single_run(
    db, auth_doctor, patient_user, default_clinic
):
    """A huge backlog must not become one unbounded transaction."""

    await _seed(
        db,
        auth_doctor["user"].id,
        default_clinic.id,
        patient_user.id,
        age_days=RETENTION_DAYS + 10,
        count=25,
    )

    deleted = await purge_expired_phi_access_logs(
        db=db, retention_days=RETENTION_DAYS, batch_size=5, max_batches=2
    )

    assert deleted == 10, "run exceeded its batch ceiling"
    # The remainder is still there, for the next scheduled run.
    assert await count_expired_phi_access_logs(
        db=db, retention_days=RETENTION_DAYS
    ) == 15


@pytest.mark.asyncio
async def test_purge_is_a_no_op_on_an_empty_table(db):
    deleted = await purge_expired_phi_access_logs(
        db=db, retention_days=RETENTION_DAYS, batch_size=100, max_batches=10
    )
    assert deleted == 0


def test_retention_setting_rejects_a_dangerously_short_window():
    """A typo of 30 days would delete almost the whole trail on the next run."""

    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings(PHI_ACCESS_LOG_RETENTION_DAYS=30)


def test_retention_defaults_to_six_years():
    from app.config import get_settings

    assert get_settings().PHI_ACCESS_LOG_RETENTION_DAYS == 2190

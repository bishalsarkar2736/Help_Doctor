"""Notification storage: the index every read needs, and a bound on growth.

notifications.user_id had a foreign key and no index, and the only index
containing it leads with event_id — so listing a user's notifications, counting
their unread and /sync were sequential scans of a table that nothing ever
pruned. Two problems that compound: the scan gets slower precisely because the
table never shrinks.

These tests pin the index (declared, present, and actually chosen by the
planner) and the retention rule (age only, nothing recent, repeatable).
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, inspect, select, text

from app.core.time import utc_now
from app.models.notification import Notification, NotificationCategory
from app.models.outbox_event import OutboxEvent
from app.models.user import User, UserRole
from app.services.notification_retention_service import (
    count_expired_notifications,
    purge_expired_notifications,
)

RETENTION_DAYS = 365
INDEX = "ix_notifications_user_id_created_at"


@pytest.fixture
async def recipient(db):
    user = User(
        email="retention-user@example.com", full_name="Retention User",
        hashed_password="x", role=UserRole.PATIENT, is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _notification(db, user, *, age_days: float, read: bool = False):
    """One notification, aged by setting created_at explicitly.

    created_at has a server default of now(), so an explicit value is required
    to place a row outside the window at all.
    """
    event = OutboxEvent(
        id=uuid.uuid4(),
        event_type="APPOINTMENT_STATUS_CHANGED",
        payload={},
        status="processed",
    )
    db.add(event)
    await db.flush()

    created = utc_now() - timedelta(days=age_days)

    notification = Notification(
        user_id=user.id,
        title="t",
        message="m",
        category=NotificationCategory.APPOINTMENT,
        event_id=event.id,
        created_at=created,
        read_at=created if read else None,
    )
    db.add(notification)
    await db.flush()

    return notification


async def _purge(db, *, days=RETENTION_DAYS, batch_size=1000, max_batches=50):
    return await purge_expired_notifications(
        db=db,
        retention_days=days,
        batch_size=batch_size,
        max_batches=max_batches,
    )


async def _surviving_ids(db, user):
    return set(
        (
            await db.scalars(
                select(Notification.id).where(Notification.user_id == user.id)
            )
        ).all()
    )


# ---------------------------------------------------------------------------
# The index
# ---------------------------------------------------------------------------


def test_the_index_is_declared_on_the_model():
    table = inspect(Notification).local_table

    index = next((i for i in table.indexes if i.name == INDEX), None)

    assert index is not None, f"{INDEX} is not declared on the model"
    assert [c.name for c in index.columns] == ["user_id", "created_at"], (
        "leading column must be user_id, or the index cannot serve "
        "WHERE user_id = ?"
    )


@pytest.mark.asyncio
async def test_the_index_exists_in_the_database(db):
    found = await db.scalar(
        text(
            "SELECT count(*) FROM pg_indexes "
            "WHERE tablename = 'notifications' AND indexname = :n"
        ),
        {"n": INDEX},
    )

    assert found == 1


@pytest.mark.asyncio
async def test_user_id_is_no_longer_covered_only_by_the_event_index(db):
    """The specific defect: uq_notification_event_user contains user_id but
    leads with event_id, so it was never usable for a per-user lookup."""
    rows = (
        await db.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'notifications'"
            )
        )
    ).all()

    leading_on_user = [
        name
        for name, definition in rows
        if definition.split("(", 1)[1].lstrip().startswith("user_id")
    ]

    assert leading_on_user, (
        "no index leads with user_id, so per-user queries still scan the table"
    )


@pytest.mark.asyncio
async def test_the_planner_uses_the_index_for_the_list_query(db):
    """Behaviour, not just presence.

    An index that exists and is not chosen fixes nothing. seqscan is disabled so
    the plan is meaningful on a small test table; what is asserted is that the
    index can serve the filter AND the ordering, with no sort step.
    """
    await db.execute(text("SET LOCAL enable_seqscan = off"))

    plan = "\n".join(
        row[0]
        for row in (
            await db.execute(
                text(
                    "EXPLAIN SELECT * FROM notifications "
                    "WHERE user_id = 1 ORDER BY created_at DESC LIMIT 50"
                )
            )
        ).all()
    )

    assert INDEX in plan, f"the list query does not use the index:\n{plan}"
    assert "Sort" not in plan, (
        f"a sort step remains, so the index is not serving the ordering:\n{plan}"
    )


# ---------------------------------------------------------------------------
# What retention deletes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_notification_older_than_the_window_is_deleted(db, recipient):
    old = await _notification(db, recipient, age_days=RETENTION_DAYS + 10)

    assert await _purge(db) == 1
    assert old.id not in await _surviving_ids(db, recipient)


@pytest.mark.asyncio
async def test_a_notification_newer_than_the_window_is_kept(db, recipient):
    recent = await _notification(db, recipient, age_days=10)

    assert await _purge(db) == 0
    assert recent.id in await _surviving_ids(db, recipient)


@pytest.mark.asyncio
async def test_an_unread_notification_inside_the_window_is_kept(db, recipient):
    """Stated as its own requirement, so asserted on its own.

    Age is the only criterion, so an unread row inside the window is never a
    candidate — but that is the property that matters, not the mechanism.
    """
    unread = await _notification(db, recipient, age_days=30, read=False)

    assert await _purge(db) == 0
    assert unread.id in await _surviving_ids(db, recipient)


@pytest.mark.asyncio
async def test_a_notification_just_inside_the_boundary_is_kept(db, recipient):
    """One day inside. The cutoff has to be a comparison, not a rounding."""
    edge = await _notification(db, recipient, age_days=RETENTION_DAYS - 1)

    assert await _purge(db) == 0
    assert edge.id in await _surviving_ids(db, recipient)


@pytest.mark.asyncio
async def test_only_the_expired_rows_go_from_a_mixed_set(db, recipient):
    """All cases together, because a predicate can be right about each one
    alone and still select the wrong set."""
    expired_read = await _notification(
        db, recipient, age_days=RETENTION_DAYS + 40, read=True
    )
    expired_unread = await _notification(
        db, recipient, age_days=RETENTION_DAYS + 20, read=False
    )
    recent_read = await _notification(db, recipient, age_days=5, read=True)
    recent_unread = await _notification(db, recipient, age_days=5, read=False)

    deleted = await _purge(db)
    survivors = await _surviving_ids(db, recipient)

    assert deleted == 2
    assert expired_read.id not in survivors
    assert expired_unread.id not in survivors
    assert recent_read.id in survivors
    assert recent_unread.id in survivors


@pytest.mark.asyncio
async def test_an_old_unread_notification_is_also_deleted(db, recipient):
    """Documenting the policy rather than discovering it later.

    Sparing unread rows would exempt exactly the accounts that grow worst — an
    abandoned account never reads anything, so "unread" would be permanent
    rather than temporary. Age is the only criterion. If that is wrong, it is a
    policy decision to change deliberately, and this test is where it shows.
    """
    stale = await _notification(
        db, recipient, age_days=RETENTION_DAYS + 100, read=False
    )

    assert await _purge(db) == 1
    assert stale.id not in await _surviving_ids(db, recipient)


# ---------------------------------------------------------------------------
# Safe to run repeatedly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_second_run_deletes_nothing_more(db, recipient):
    """It runs nightly forever, so this is the ordinary case."""
    await _notification(db, recipient, age_days=RETENTION_DAYS + 5)
    await _notification(db, recipient, age_days=1)

    assert await _purge(db) == 1
    assert await _purge(db) == 0
    assert await _purge(db) == 0

    assert len(await _surviving_ids(db, recipient)) == 1


@pytest.mark.asyncio
async def test_an_empty_table_is_not_an_error(db, recipient):
    assert await _purge(db) == 0


@pytest.mark.asyncio
async def test_the_count_helper_agrees_with_what_is_deleted(db, recipient):
    for age in (RETENTION_DAYS + 1, RETENTION_DAYS + 2, 3):
        await _notification(db, recipient, age_days=age)

    expected = await count_expired_notifications(
        db=db, retention_days=RETENTION_DAYS
    )

    assert expected == 2
    assert await _purge(db) == expected


@pytest.mark.asyncio
async def test_the_batch_ceiling_bounds_one_run(db, recipient):
    """A first run against a backlog must stop, leaving the rest for the next
    run rather than becoming one unbounded transaction."""
    for index in range(5):
        await _notification(db, recipient, age_days=RETENTION_DAYS + 10 + index)

    deleted = await _purge(db, batch_size=2, max_batches=1)

    assert deleted == 2
    assert await db.scalar(select(func.count(Notification.id))) == 3

    # The remainder is picked up by a later run.
    assert await _purge(db, batch_size=2, max_batches=50) == 3


@pytest.mark.asyncio
async def test_batching_deletes_everything_expired_across_batches(
    db, recipient
):
    for index in range(7):
        await _notification(db, recipient, age_days=RETENTION_DAYS + 10 + index)

    assert await _purge(db, batch_size=3, max_batches=50) == 7
    assert await _surviving_ids(db, recipient) == set()


@pytest.mark.asyncio
async def test_a_shorter_window_deletes_more(db, recipient):
    """The cutoff follows the setting rather than being baked in."""
    await _notification(db, recipient, age_days=60)

    assert await _purge(db, days=365) == 0
    assert await _purge(db, days=30) == 1


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


def test_the_purge_is_on_the_beat_schedule():
    from app.core.celery import celery_app
    import app.task.notification_retention  # noqa: F401

    entry = celery_app.conf.beat_schedule.get("notification-retention")

    assert entry is not None, "retention is not scheduled"
    assert entry["task"] in celery_app.tasks, (
        f"beat schedules {entry['task']}, which is not a registered task"
    )
    assert "app.task.notification_retention" in celery_app.conf.include

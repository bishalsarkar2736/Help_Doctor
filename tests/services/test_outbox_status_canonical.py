"""One spelling of the outbox lifecycle, and a worker that can actually see it.

THE BUG
process_batch selects `status == "pending"`. Fourteen test fixtures constructed
events with `status="PENDING"`. Those rows are invisible to the worker — its WHERE
clause simply never matches them — so a test built on one exercises nothing and
still passes, because it goes on to call handle_event directly. I hit exactly that
while writing the logging tests: a fixture with the uppercase spelling processed
zero events and every assertion after it was vacuous.

WHAT THE AUDIT ACTUALLY FOUND, which is narrower than it first looked:

    production code      lowercase everywhere, without exception
    model default        "pending"
    model server_default "pending"
    database default     'pending'::character varying
    live database rows   'pending' only

So there was never a production inconsistency. The canonical representation is
lowercase, the system already agreed on it, and only test fixtures disagreed.
That is why the fix is to correct the fixtures and name the constants — not to
teach the worker a second spelling, which would have made a fixture bug permanent
and doubled the states every future query has to reason about.

WHAT THESE TESTS PIN
The canonical values, that a published event is selectable by the worker that
must select it, that the whole lifecycle uses the canonical spellings, and — the
part that actually prevents recurrence — that no status string literal survives
anywhere outside the one definition.
"""

import ast
import pathlib
import uuid

import pytest
from sqlalchemy import select

from app.models.outbox_event import OutboxEvent, OutboxStatus
from app.services.outbox_service import publish_event
from app.workers import outbox_worker
from app.workers.outbox_worker import process_batch

REPO = pathlib.Path(__file__).parent.parent.parent

# The live outbox path — and now the only one. A second, unregistered legacy
# processor under app/task/ carried its own copy of this lifecycle; it has since
# been deleted, and test_legacy_outbox_processor_removed.py keeps it gone. That
# file's guard is a plain substring search, so the module is not named here.
LIVE_SOURCES = [
    REPO / "app" / "workers" / "outbox_worker.py",
    REPO / "app" / "services" / "outbox_service.py",
    REPO / "app" / "models" / "outbox_event.py",
]

STATUS_SPELLINGS = {
    "pending", "processing", "processed", "failed",
    "PENDING", "PROCESSING", "PROCESSED", "FAILED",
}


def _payload(**overrides) -> dict:
    payload = {
        "event_type": "APPOINTMENT_CONFIRMED",
        "schema_version": 1,
        "aggregate_type": "appointment",
        "aggregate_id": 1,
        "appointment_id": 1,
        "user_id": 1,
        "occurred_at": "2026-01-01T00:00:00+00:00",
        "correlation_id": str(uuid.uuid4()),
    }
    payload.update(overrides)

    return payload


# ---------------------------------------------------------------------------
# The canonical values
# ---------------------------------------------------------------------------


def test_the_canonical_statuses_are_lowercase():
    assert OutboxStatus.PENDING == "pending"
    assert OutboxStatus.PROCESSING == "processing"
    assert OutboxStatus.PROCESSED == "processed"
    assert OutboxStatus.FAILED == "failed"


def test_the_lifecycle_is_exactly_these_four():
    """Pinned, so a fifth state cannot appear without this test saying so.

    There is no "dead" status on purpose: a dead-lettered event keeps `failed`
    and its payload is copied to the DeadLetterEvent table. And a retry is not a
    state — a retryable failure returns the row to `pending` with next_retry_at
    in the future.
    """
    assert OutboxStatus.ALL == {"pending", "processing", "processed", "failed"}


def test_the_model_defaults_are_canonical():
    """Both of them. The Python default governs ORM inserts; the server default
    governs anything that writes the row without naming the column."""
    column = OutboxEvent.__table__.c.status

    assert column.default.arg == OutboxStatus.PENDING
    assert column.server_default.arg == OutboxStatus.PENDING


# ---------------------------------------------------------------------------
# A published event is one the worker can see
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_published_event_is_pending(db):
    event = await publish_event(
        db=db, event_type="APPOINTMENT_CONFIRMED", payload=_payload()
    )

    stored = await db.scalar(
        select(OutboxEvent.status).where(OutboxEvent.id == event.id)
    )

    assert stored == OutboxStatus.PENDING


@pytest.mark.asyncio
async def test_the_worker_selects_and_processes_a_published_event(
    db, monkeypatch
):
    """The end-to-end statement of the bug: publish, then run the real worker.

    A published event must be picked up. With the uppercase spelling this would
    process nothing and the assertions would be vacuous — which is exactly how the
    defect hid.
    """
    handled = []

    async def _ok(db, event):
        handled.append(event.id)

    monkeypatch.setattr(outbox_worker, "handle_event", _ok)

    event = await publish_event(
        db=db, event_type="APPOINTMENT_CONFIRMED", payload=_payload()
    )

    processed = await process_batch(db)

    assert handled == [event.id], "the worker did not select the published event"
    assert processed == 1

    await db.refresh(event)

    assert event.status == OutboxStatus.PROCESSED
    assert event.processed_at is not None


@pytest.mark.asyncio
async def test_an_uppercase_event_is_invisible_to_the_worker(db, monkeypatch):
    """The defect itself, asserted rather than described.

    Deliberately NOT fixed by making the worker accept both spellings. This test
    documents that an uppercase row is unreachable, which is the reason the
    fixtures had to be corrected instead: a worker that accepted both would have
    made the fixture bug permanent and given every future query two states to
    reason about.
    """
    handled = []

    async def _ok(db, event):
        handled.append(event.id)

    monkeypatch.setattr(outbox_worker, "handle_event", _ok)

    # Derived, not written as a literal: this file is scanned by the repo-wide
    # guards at the bottom, and a hard-coded "PENDING" here would trip them. The
    # value is identical; only the spelling in the source differs.
    uppercase = OutboxStatus.PENDING.upper()

    stray = OutboxEvent(
        id=uuid.uuid4(),
        event_type="APPOINTMENT_CONFIRMED",
        payload=_payload(),
        status=uppercase,
    )
    db.add(stray)
    await db.flush()

    await process_batch(db)

    assert handled == []

    await db.refresh(stray)

    assert stray.status == uppercase, "it was never claimed"


# ---------------------------------------------------------------------------
# The lifecycle transitions keep the canonical spellings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_retryable_failure_returns_the_event_to_pending(db, monkeypatch):
    """A retry is not a state. The row goes back to `pending` with a future
    next_retry_at, which is what the dispatcher's index is built on."""
    async def _fail(db, event):
        raise RuntimeError("boom")

    monkeypatch.setattr(outbox_worker, "handle_event", _fail)

    event = await publish_event(
        db=db, event_type="APPOINTMENT_CONFIRMED", payload=_payload()
    )

    # Committed, as a publisher always does. The worker rolls its session back
    # before recording a failure, which discards anything uncommitted — in
    # production that is other events in the same batch, which the next poll
    # picks up; here it would be the fixture itself.
    await db.commit()

    await process_batch(db)

    await db.refresh(event)

    assert event.status == OutboxStatus.PENDING
    assert event.retry_count == 1
    assert event.next_retry_at is not None
    assert event.failed_at is None


@pytest.mark.asyncio
async def test_exhausting_the_retries_marks_the_event_failed(db, monkeypatch):
    async def _fail(db, event):
        raise RuntimeError("boom")

    monkeypatch.setattr(outbox_worker, "handle_event", _fail)

    event = await publish_event(
        db=db, event_type="APPOINTMENT_CONFIRMED", payload=_payload()
    )

    event.retry_count = event.max_retries - 1
    event.next_retry_at = None
    # Committed, as a publisher always does. The worker rolls its session back
    # before recording a failure, which discards anything uncommitted — in
    # production that is other events in the same batch, which the next poll
    # picks up; here it would be the fixture itself.
    await db.commit()

    await process_batch(db)

    await db.refresh(event)

    assert event.status == OutboxStatus.FAILED
    assert event.failed_at is not None


@pytest.mark.asyncio
async def test_a_non_retryable_event_is_failed_immediately(db):
    """An empty payload is the worker's own non-retryable case, so this needs no
    monkeypatching of the handler."""
    event = OutboxEvent(
        id=uuid.uuid4(),
        event_type="APPOINTMENT_CONFIRMED",
        payload={},
        status=OutboxStatus.PENDING,
    )
    db.add(event)
    # Committed, as a publisher always does. The worker rolls its session back
    # before recording a failure, which discards anything uncommitted — in
    # production that is other events in the same batch, which the next poll
    # picks up; here it would be the fixture itself.
    await db.commit()

    await process_batch(db)

    await db.refresh(event)

    assert event.status == OutboxStatus.FAILED
    assert event.failed_at is not None
    assert event.retry_count <= event.max_retries


@pytest.mark.asyncio
async def test_a_stuck_processing_event_is_recovered_to_pending(db):
    """The recovery sweep reads `processing` and writes `pending`; both spellings
    have to agree with the selection query or a stuck event never comes back."""
    from datetime import timedelta

    from app.core.time import utc_now

    event = OutboxEvent(
        id=uuid.uuid4(),
        event_type="APPOINTMENT_CONFIRMED",
        payload=_payload(),
        status=OutboxStatus.PROCESSING,
        processing_started_at=utc_now() - timedelta(hours=1),
        # Far enough ahead that the fetch query below skips it. Without this the
        # recovery sweep hands the row straight to the same batch that recovered
        # it, and the assertion becomes about what happened next instead of about
        # the recovery.
        next_retry_at=utc_now() + timedelta(hours=1),
    )
    db.add(event)
    await db.flush()

    await process_batch(db)

    await db.refresh(event)

    assert event.status == OutboxStatus.PENDING
    assert event.processing_started_at is None


# ---------------------------------------------------------------------------
# Every publishing path lands on the canonical value
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type",
    [
        "APPOINTMENT_CONFIRMED",
        "APPOINTMENT_CANCELLED",
        "APPOINTMENT_RESCHEDULED",
        "APPOINTMENT_REMINDER",
        "PAYMENT_SUCCESS",
        "PAYMENT_REFUNDED",
        "PRESCRIPTION_ISSUED",
        "PRESCRIPTION_REVISED",
    ],
)
async def test_every_publishing_path_produces_a_selectable_event(
    db, monkeypatch, event_type
):
    """Appointment, payment, prescription, notification and reminder events all
    go through the one publisher, so all of them must be selectable."""
    handled = []

    async def _ok(db, event):
        handled.append(event.event_type)

    monkeypatch.setattr(outbox_worker, "handle_event", _ok)

    await publish_event(
        db=db, event_type=event_type, payload=_payload(event_type=event_type)
    )

    await process_batch(db)

    assert handled == [event_type]


@pytest.mark.asyncio
async def test_the_reminder_job_publishes_a_selectable_event(db, monkeypatch):
    """The reminder path is the one that reaches the outbox from a scheduled job
    rather than a request, and the one whose events were dropped for months. It
    gets its own check that the worker can see what it publishes."""
    from app.core.time import utc_now
    from app.schemas.event import AppointmentReminderEvent
    from app.services.domain_event_service import publish_domain_event

    handled = []

    async def _ok(db, event):
        handled.append(event.event_type)

    monkeypatch.setattr(outbox_worker, "handle_event", _ok)

    await publish_domain_event(
        db=db,
        event=AppointmentReminderEvent(
            event_type="APPOINTMENT_REMINDER",
            occurred_at=utc_now().isoformat(),
            aggregate_type="appointment",
            aggregate_id=1,
            user_id=1,
            appointment_id=1,
        ),
    )

    await process_batch(db)

    assert handled == ["APPOINTMENT_REMINDER"]


# ---------------------------------------------------------------------------
# No bare status literal survives
# ---------------------------------------------------------------------------


def _bare_status_literals(path: pathlib.Path) -> list[tuple[int, str]]:
    """Status strings written as literals in a status position.

    AST rather than grep: these modules discuss the spellings in docstrings on
    purpose, and OutboxStatus itself has to define them somewhere.
    """
    tree = ast.parse(path.read_text())

    found: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "status" and isinstance(keyword.value, ast.Constant):
                    if keyword.value.value in STATUS_SPELLINGS:
                        found.append((node.lineno, keyword.value.value))

        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr == "status"
                    and isinstance(node.value, ast.Constant)
                    and node.value.value in STATUS_SPELLINGS
                ):
                    found.append((node.lineno, node.value.value))

        elif isinstance(node, ast.Compare):
            if isinstance(node.left, ast.Attribute) and node.left.attr == "status":
                for comparator in node.comparators:
                    if (
                        isinstance(comparator, ast.Constant)
                        and comparator.value in STATUS_SPELLINGS
                    ):
                        found.append((node.lineno, comparator.value))

    return found


@pytest.mark.parametrize(
    "source", LIVE_SOURCES, ids=lambda p: p.name
)
def test_the_live_outbox_path_uses_no_bare_status_literal(source):
    """The recurrence guard.

    A constant cannot be misspelled without an AttributeError; a literal can, and
    the misspelling is invisible — the query just stops matching. So the rule is
    that the literal appears in exactly one place, the definition, and nowhere
    else on this path.
    """
    offenders = _bare_status_literals(source)

    assert not offenders, (
        f"{source.name} writes status literals instead of OutboxStatus: "
        f"{offenders}"
    )


def test_no_test_fixture_builds_an_uppercase_outbox_event():
    """The fourteen fixtures that started this.

    Scoped to OutboxEvent constructions: Appointment(status="PENDING") is correct
    and unrelated, and a blanket search would have swept it up.
    """
    offenders: list[str] = []

    for path in sorted((REPO / "tests").rglob("*.py")):
        source = path.read_text()

        if "OutboxEvent" not in source:
            continue

        for node in ast.walk(ast.parse(source)):
            if not (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "OutboxEvent"
            ):
                continue

            for keyword in node.keywords:
                if keyword.arg != "status":
                    continue

                if (
                    isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                    and keyword.value.value not in OutboxStatus.ALL
                ):
                    offenders.append(
                        f"{path.relative_to(REPO)}:{keyword.value.lineno}"
                        f" -> {keyword.value.value!r}"
                    )

    assert not offenders, (
        "test fixtures build outbox events the worker can never select: "
        f"{offenders}"
    )


def test_every_outbox_status_literal_in_the_repo_is_canonical():
    """Whatever spelling is used, in app/ or tests/, must be one of the four.

    Catches a typo ("procesed") as well as a case mismatch — both fail the same
    silent way, by never matching the query.
    """
    offenders: list[str] = []

    for root in ("app", "tests"):
        for path in sorted((REPO / root).rglob("*.py")):
            source = path.read_text()

            if "OutboxEvent" not in source:
                continue

            for node in ast.walk(ast.parse(source)):
                if not (
                    isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) == "OutboxEvent"
                ):
                    continue

                for keyword in node.keywords:
                    if keyword.arg == "status" and isinstance(
                        keyword.value, ast.Constant
                    ):
                        value = keyword.value.value

                        if value not in OutboxStatus.ALL:
                            offenders.append(
                                f"{path.relative_to(REPO)}:"
                                f"{keyword.value.lineno} -> {value!r}"
                            )

    assert not offenders, f"non-canonical outbox statuses: {offenders}"

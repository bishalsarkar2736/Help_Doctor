"""There is one outbox processor, and the old one cannot come back.

WHAT WAS DELETED
app/task/outbox_tasks_old.py — a complete second outbox implementation: its own
Celery task (`process_outbox_events`), its own pending → processing →
processed/failed lifecycle, its own retry backoff, and its own event dispatcher
handling five event types by hand.

WHY IT WAS SAFE TO DELETE, established before removing it:

    app/task/__init__.py                  empty (0 bytes) — importing the package
                                          does not import the module
    celery_app.conf.include               seven modules, not this one
    beat_schedule                         six entries, none referencing it
    autodiscover_tasks                    never called
    docker-compose worker command         `celery -A app.core.celery worker`,
                                          no --include
    references in the whole repository    none, in any file type

    and the decisive one: after `celery_app.loader.import_default_modules()` —
    exactly what `celery -A app.core.celery worker` does at startup — the task
    name `process_outbox_events` was absent from celery_app.tasks.

A Celery task only exists if its module is imported. Nothing imported this one,
so nothing could send to it and no worker could have consumed it.

WHY IT MATTERED THAT IT WENT
It was not merely unused. It was a divergent copy: it dispatched on lowercase
`payment_success`, knew nothing of the schema registry, the dead-letter table, the
stuck-event recovery sweep, the notification receipts or any channel added since.
Anyone reading it for "how does the outbox work?" would have learnt a system that
has not existed for a long time.
"""

import ast
import importlib
import pathlib

import pytest

from app.core.celery import celery_app
from app.models.outbox_event import OutboxEvent

REPO = pathlib.Path(__file__).parent.parent.parent

LEGACY_MODULE = "app.task.outbox_tasks_old"
LEGACY_PATH = REPO / "app" / "task" / "outbox_tasks_old.py"
LEGACY_TASK = "process_outbox_events"

ACTIVE_WORKER = REPO / "app" / "workers" / "outbox_worker.py"

# The only files permitted to write the legacy names: the two whose job is to
# assert their absence. Kept as an explicit, short list rather than exempting
# "anything under tests/", and rather than splitting the literal to sneak past a
# guard this file owns — a reader should be able to see exactly who may say it.
ALLOWED_TO_NAME_IT = {
    (REPO / "tests" / "services" / "test_legacy_outbox_processor_removed.py").resolve(),
    (REPO / "tests" / "deployment" / "test_outbox_worker_service.py").resolve(),
}


@pytest.fixture(scope="module")
def worker_started():
    """The Celery app as a real worker leaves it.

    conf.include is imported lazily at worker startup, so a registry inspected
    without this is empty and would "prove" the absence of every task.
    """
    celery_app.loader.import_default_modules()

    return celery_app


# ---------------------------------------------------------------------------
# It is gone
# ---------------------------------------------------------------------------


def test_the_legacy_module_file_does_not_exist():
    assert not LEGACY_PATH.exists()


def test_the_legacy_module_cannot_be_imported():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(LEGACY_MODULE)


def test_no_file_in_the_repository_mentions_it():
    """Text search on purpose, over every tracked source file.

    A Celery task can be invoked by NAME as a bare string —
    send_task("process_outbox_events") — which no import graph or AST walk of
    call sites would reveal. So this one is deliberately a substring search, and
    it covers yaml, Dockerfiles and shell as well as Python.
    """
    haystacks = []

    for pattern in ("*.py", "*.yml", "*.yaml", "*.sh", "*.toml", "*.cfg", "*.ini",
                    "*.md", "Dockerfile*", "Makefile"):
        haystacks.extend(REPO.rglob(pattern))

    offenders = []

    for path in haystacks:
        parts = set(path.parts)

        if parts & {"venv", ".git", "__pycache__", "node_modules", ".pytest_cache"}:
            continue

        if path.resolve() in ALLOWED_TO_NAME_IT:
            continue

        try:
            text = path.read_text(errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue

        if "outbox_tasks_old" in text or LEGACY_TASK in text:
            offenders.append(str(path.relative_to(REPO)))

    assert not offenders, f"the legacy processor is still referenced: {offenders}"


# ---------------------------------------------------------------------------
# Celery does not know about it
# ---------------------------------------------------------------------------


def test_the_legacy_task_is_not_registered(worker_started):
    """The strongest single statement: a worker started the production way does
    not have this task in its registry, so nothing can dispatch to it."""
    assert LEGACY_TASK not in worker_started.tasks


def test_the_include_list_does_not_load_it(worker_started):
    assert LEGACY_MODULE not in list(worker_started.conf.include)

    for module in worker_started.conf.include:
        assert "outbox_tasks_old" not in module


def test_no_beat_entry_schedules_it(worker_started):
    for name, entry in worker_started.conf.beat_schedule.items():
        assert entry["task"] != LEGACY_TASK, f"beat entry {name!r} schedules it"
        assert "outbox" not in entry["task"], (
            f"beat entry {name!r} schedules an outbox task: {entry['task']}"
        )


def test_every_scheduled_task_still_resolves(worker_started):
    """Deleting a module is a way to break Beat. Every scheduled task must still
    exist in the registry — a name Beat cannot resolve fails at dispatch time,
    which is a runtime error nothing here would otherwise catch."""
    missing = {
        entry["task"]
        for entry in worker_started.conf.beat_schedule.values()
        if entry["task"] not in worker_started.tasks
    }

    assert not missing, f"beat schedules unregistered tasks: {missing}"


def test_the_surviving_task_registry_is_unchanged(worker_started):
    """Pinned, so this deletion cannot be shown to have removed anything else."""
    registered = {
        name for name in worker_started.tasks if not name.startswith("celery.")
    }

    assert registered == {
        "app.tasks.appointment_no_show.mark_no_show_task",
        "app.tasks.notification_reminders.send_appointment_reminders_task",
        "app.tasks.notification_retention.notification_purge_task",
        "app.tasks.payment_reconciliation.payment_reconciliation_task",
        "app.tasks.phi_access_retention.phi_access_log_purge_task",
        "app.tasks.slot_generation.generate_slots_task",
        "send_push_notification_task",
    }


# ---------------------------------------------------------------------------
# Exactly one processor remains
# ---------------------------------------------------------------------------


def _is_outbox_processor(path: pathlib.Path) -> bool:
    """A module that both SELECTS outbox rows and MUTATES their status.

    That pair is what makes something a processor, as opposed to a publisher
    (outbox_service creates rows and never advances them) or a reader.
    """
    try:
        tree = ast.parse(path.read_text())
    except (SyntaxError, UnicodeDecodeError):
        return False

    selects = False
    mutates = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "status":
            if getattr(node.value, "id", None) == "OutboxEvent":
                selects = True

        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr == "status":
                    base = getattr(target.value, "id", "")
                    if base in {"event", "outbox_event"}:
                        mutates = True

    return selects and mutates


def test_only_one_module_processes_the_outbox():
    """The point of the deletion, asserted structurally.

    Two processors is not merely redundant — they race for the same rows under
    SKIP LOCKED and advance them through two different lifecycles.
    """
    processors = [
        path.relative_to(REPO)
        for path in sorted((REPO / "app").rglob("*.py"))
        if _is_outbox_processor(path)
    ]

    assert processors == [ACTIVE_WORKER.relative_to(REPO)], (
        f"expected one outbox processor, found: {processors}"
    )


def test_the_active_worker_is_untouched_and_complete():
    """A sanity check on the survivor: the deletion must not have taken any of
    the live worker's lifecycle with it."""
    source = ACTIVE_WORKER.read_text()

    for marker in (
        "async def process_batch",
        "async def handle_event",
        "DeadLetterEvent",
        "NonRetryableError",
        "EVENT_SCHEMAS",
        "dispatch_event",
    ):
        assert marker in source, f"the active worker lost {marker}"


# ---------------------------------------------------------------------------
# Every publishing path still reaches the one dispatcher
# ---------------------------------------------------------------------------


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
def test_every_live_event_type_is_known_to_the_surviving_dispatcher(event_type):
    """The deleted module carried its own hand-written dispatcher for five event
    types. Everything must now be served by the registry the live worker uses —
    appointment, payment, prescription, notification, WhatsApp and reminder
    events alike."""
    from app.schemas.event_registry import EVENT_SCHEMAS
    from app.services.event_handlers.dispatcher import EVENT_HANDLERS

    assert event_type in EVENT_SCHEMAS
    assert event_type in EVENT_HANDLERS


@pytest.mark.asyncio
async def test_publishing_still_reaches_the_active_worker(db, monkeypatch):
    """End to end through the surviving path: publish, then let the real worker
    select and process it."""
    import uuid

    from app.services.outbox_service import publish_event
    from app.workers import outbox_worker
    from app.workers.outbox_worker import process_batch

    handled = []

    async def _ok(db, event):
        handled.append(event.event_type)

    monkeypatch.setattr(outbox_worker, "handle_event", _ok)

    await publish_event(
        db=db,
        event_type="APPOINTMENT_REMINDER",
        payload={
            "event_type": "APPOINTMENT_REMINDER",
            "schema_version": 1,
            "aggregate_type": "appointment",
            "aggregate_id": 1,
            "appointment_id": 1,
            "user_id": 1,
            "occurred_at": "2026-01-01T00:00:00+00:00",
            "correlation_id": str(uuid.uuid4()),
        },
    )

    processed = await process_batch(db)

    assert handled == ["APPOINTMENT_REMINDER"]
    assert processed == 1

    assert OutboxEvent is not None  # the model survives the deletion

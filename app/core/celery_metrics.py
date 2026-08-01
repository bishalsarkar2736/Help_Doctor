"""Prometheus metrics for the Celery worker.

Background jobs previously failed silently. The API exports metrics, but a
Celery worker is a different process — nothing scraped it — so appointment
reminders, slot generation, payment reconciliation and the PHI retention purge
could stop entirely and the only evidence would be a log line nobody reads.

THE PREFORK PROBLEM
-------------------
The worker runs prefork with CELERY_WORKER_CONCURRENCY children. Task signals
fire in the CHILDREN, while an HTTP server can only be started once, in the
parent. A counter incremented in a child is invisible to a plain registry in
the parent, so the naive version of this file exports zeros forever and looks
like a worker doing nothing.

prometheus_client solves this with multiprocess mode: every process writes to
mmap'd files in PROMETHEUS_MULTIPROC_DIR, and the parent serves the aggregate.
That mode is enabled ONLY for the worker (set in docker-compose.yml) — the API
is a single process and its own /metrics endpoint must keep working normally.

Consequences of multiprocess mode:

* Gauges need an explicit multiprocess_mode, because "the current value" is
  ambiguous when several processes each have one.

* The directory must be empty when the process starts, or metrics from dead
  workers of a previous run are aggregated into this one's totals forever.
  That cleanup MUST happen before Python imports this module — the compose
  command does it, and the tmpfs mount makes it moot there anyway.

  It is deliberately NOT done from a Celery signal. An earlier version cleared
  the directory on celeryd_init, which fires AFTER these metrics have already
  opened their mmap files: the files were unlinked while the handles stayed
  open, so every subsequent write went to a deleted inode and the collector
  reported a permanent 0.0 — a live worker indistinguishable from a dead one.
"""

import logging
import os
import time

from celery.signals import (
    task_failure,
    task_postrun,
    task_prerun,
    task_retry,
    worker_ready,
    worker_shutdown,
)
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from prometheus_client import multiprocess, start_http_server

logger = logging.getLogger(__name__)

METRICS_PORT = int(os.getenv("CELERY_METRICS_PORT", "9100"))

# --- metrics ---------------------------------------------------------------

celery_tasks_total = Counter(
    "celery_tasks_total",
    "Celery tasks by name and terminal state",
    ["task", "state"],
)

celery_task_duration_seconds = Histogram(
    "celery_task_duration_seconds",
    "Task execution time",
    ["task"],
    # Tuned for these jobs: reminders and reconciliation are sub-second, the
    # PHI retention purge is minutes. The default buckets top out at 10s and
    # would put every purge in +Inf.
    buckets=(0.05, 0.1, 0.5, 1, 5, 15, 60, 300, 900),
)

# 'livesum' so several children each reporting 1 add up to the number of live
# workers, rather than one arbitrarily winning.
celery_worker_up = Gauge(
    "celery_worker_up",
    "1 per live worker process",
    multiprocess_mode="livesum",
)

celery_worker_heartbeat_timestamp = Gauge(
    "celery_worker_heartbeat_timestamp",
    "Unix time when a worker last reported ready",
    multiprocess_mode="max",
)


class QueueDepthCollector:
    """Reads broker queue depth at scrape time.

    Queue depth is deliberately NOT a Gauge some task sets on a schedule: if
    the workers are wedged — the exact situation a backlog alert exists to
    catch — the sampling task never runs and the gauge reports the last healthy
    value forever. Reading Redis when Prometheus scrapes means the number is
    only ever as stale as the scrape interval, and it keeps working when
    nothing is being consumed at all.
    """

    QUEUES = ("celery",)

    def collect(self):
        from prometheus_client.core import GaugeMetricFamily

        family = GaugeMetricFamily(
            "celery_queue_length",
            "Messages waiting in a broker queue",
            labels=["queue"],
        )

        try:
            import redis

            client = redis.Redis.from_url(
                os.getenv("REDIS_URL", "redis://redis:6379/0")
            )
            for queue in self.QUEUES:
                family.add_metric([queue], client.llen(queue))
        except Exception:
            # Never let a broker hiccup break the whole metrics endpoint —
            # losing every other metric because one is unavailable would be a
            # worse outage than the one being reported.
            logger.warning("could not read celery queue depth", exc_info=True)
            return

        yield family

# Task start times, keyed by task id, so postrun can measure duration. Local to
# the child that ran the task, which is where both signals fire.
_started_at: dict[str, float] = {}


# --- signal handlers --------------------------------------------------------


@worker_ready.connect
def _worker_ready(**_kwargs) -> None:
    celery_worker_up.inc()
    celery_worker_heartbeat_timestamp.set(time.time())

    # Served from the parent, aggregating every child's mmap'd files.
    try:
        registry = CollectorRegistry()
        # Aggregates the mmap'd files every child writes to.
        multiprocess.MultiProcessCollector(registry)
        # Queue depth is read live on scrape, not from those files.
        registry.register(QueueDepthCollector())
        start_http_server(METRICS_PORT, registry=registry)
        logger.info("celery metrics server listening on %s", METRICS_PORT)
    except OSError:
        # Already bound. Harmless when the worker restarts in place; must not
        # take the worker down over metrics.
        logger.warning("celery metrics port %s already in use", METRICS_PORT)


@worker_shutdown.connect
def _worker_shutdown(**_kwargs) -> None:
    celery_worker_up.dec()


@task_prerun.connect
def _task_prerun(task_id=None, task=None, **_kwargs) -> None:
    _started_at[task_id] = time.perf_counter()
    celery_tasks_total.labels(task=getattr(task, "name", "unknown"), state="started").inc()


@task_postrun.connect
def _task_postrun(task_id=None, task=None, state=None, **_kwargs) -> None:
    name = getattr(task, "name", "unknown")

    started = _started_at.pop(task_id, None)
    if started is not None:
        celery_task_duration_seconds.labels(task=name).observe(
            time.perf_counter() - started
        )

    # postrun fires for every outcome; task_failure below counts failures
    # separately, so only success is recorded here to avoid double counting.
    if state == "SUCCESS":
        celery_tasks_total.labels(task=name, state="succeeded").inc()


@task_failure.connect
def _task_failure(sender=None, **_kwargs) -> None:
    celery_tasks_total.labels(
        task=getattr(sender, "name", "unknown"), state="failed"
    ).inc()


@task_retry.connect
def _task_retry(sender=None, **_kwargs) -> None:
    celery_tasks_total.labels(
        task=getattr(sender, "name", "unknown"), state="retried"
    ).inc()

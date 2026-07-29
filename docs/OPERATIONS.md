# Operations Runbook

Day-2 operations: background jobs, backups, monitoring, health, and common
incident procedures.

---

## Background jobs (Celery)

Configuration: [`app/core/celery.py`](../app/core/celery.py). Tasks live in
[`app/task/`](../app/task/).

### Scheduled (beat) jobs

| Schedule        | Task                                   | Effect |
|-----------------|----------------------------------------|--------|
| every 60s       | `send_appointment_reminders_task`      | Emits reminder events for appointments ~60 min out. |
| every 300s (5m) | `payment_reconciliation_task`          | Reconciles pending payments against the gateway. |
| every 3600s (1h)| `generate_slots_task`                  | Generates upcoming doctor slots. |

The reminder job takes a **Postgres advisory lock** before running, so even if
more than one beat/worker were mistakenly active, the job body runs once. Still,
**run only one beat process.**

### On-demand tasks

- `send_push_notification_task` — web-push delivery with retry/backoff, invoked
  from the notification service.

### Operating

```bash
# Start
celery -A app.core.celery worker --loglevel=info
celery -A app.core.celery beat   --loglevel=info

# Inspect
celery -A app.core.celery inspect active      # running tasks
celery -A app.core.celery inspect scheduled   # queued/eta tasks
```

> **Concurrency is set in config**, not on the command line —
> `CELERY_WORKER_CONCURRENCY` (default 4). Do not add `--concurrency`:
> it overrides the config and can exhaust the DB connection budget.
> See [CONFIGURATION.md](CONFIGURATION.md#celery).

If push notifications or reminders "stop working", first check that **both** the
worker and beat processes are alive and connected to Redis.

---

## Transactional outbox

Domain events are written to an `outbox_event` table in the same DB transaction
as the state change, then drained by the outbox worker
([`app/workers/run_outbox_worker.py`](../app/workers/run_outbox_worker.py)).
Failed deliveries move to a dead-letter table (`outbox_dead_letter`).

```bash
python -m app.workers.run_outbox_worker
```

If downstream effects (websocket fan-out, push) lag, verify the outbox worker is
running and check the dead-letter table for stuck events.

---

## Backups

Script: [`scripts/backup_db.sh`](../scripts/backup_db.sh). In Compose it runs
hourly via the `db_backup` service into the `db_backups` volume.

### What it does

- `pg_dump` → gzip into `$BACKUP_DIR/<db>_<UTC-timestamp>.sql.gz`
- Reads the password from `PGPASSWORD` (never on the command line)
- Fails loudly if the dump is suspiciously small (e.g. auth failed mid-pipe)
- Deletes dumps older than `RETENTION_DAYS` (default 7)

### Configuration (env)

`POSTGRES_*` (reused from the app), plus optional `BACKUP_DIR` (default
`./backups`), `RETENTION_DAYS` (default 7), and — in the Compose service —
`BACKUP_INTERVAL_SECONDS` (default 3600).

### Running manually

```bash
BACKUP_DIR=/backups RETENTION_DAYS=14 ./scripts/backup_db.sh
```

### Restoring ⚠️ test this before you need it

```bash
gunzip -c helpdoctor_db_20260722T090000Z.sql.gz \
  | psql "postgresql://<user>:<pass>@<host>:<port>/<db>"
```

> An untested backup is not a backup. Do a trial restore into a throwaway
> database at least once, and after any schema change.

### Recommended hardening

The default writes to a local volume — that's lost if the host dies. For real
durability, additionally push the dumps off-box (e.g. `aws s3 cp`, `rclone`, or
a mounted object-storage bucket) on a schedule.

---

## Failure modes & degradation

How the app behaves when a dependency fails — designed to degrade, not crash.

| Failure | Behavior |
|---|---|
| **Redis outage** | The cache ([`app/core/cache.py`](../app/core/cache.py)) **fails open** — reads return a miss and fall through to Postgres, writes are skipped; each event logs `cache_unavailable`. Rate limiting also fails open (`swallow_errors=True`), so requests are allowed rather than 500'd. The app stays up (slower, unthrottled) until Redis returns. |
| **Postgres blip** | `pool_pre_ping` + `pool_recycle` (30 min) detect and replace stale connections automatically; transient failures are retried (`with_retry`). |
| **Celery worker hard-kill (SIGKILL/OOM)** | `task_acks_late` + `task_reject_on_worker_lost` requeue the in-flight task to another worker instead of losing it. |
| **Beat/scheduler restart** | Slot generation holds a Postgres advisory lock and is idempotent, so a restart or a duplicate beat can't double-generate. |
| **Duplicate payment webhook** | Idempotency-keyed; the stored response is replayed and the payment is not processed twice. |
| **Outbox delivery failure** | Retried up to `max_retries`, then moved to the `dead_letter_events` table; stuck events are reclaimed. |

### Rate limiting across replicas
Rate-limit storage defaults to **in-memory (per process)**. With multiple app
instances, set `RATE_LIMIT_STORAGE_URI` to a shared backend (e.g.
`async+redis://host:6379`) so limits are enforced globally.

### Disaster recovery
Recovery point ≈ the backup interval (hourly by default → **RPO ≤ 1 h**; tighten
with more frequent dumps or Postgres PITR/WAL archiving). Recovery procedure is
the restore in **Backups** above — rehearse it into a throwaway DB so RTO is
known, not guessed.

### Secrets in production
Do **not** ship a `.env` to production. The app reads settings from environment
variables, so inject secrets from your platform's manager (Docker/Kubernetes
secrets, Vault, AWS Secrets Manager) as env vars or mounted files — no code
change required.

---

## Monitoring & observability

### Health endpoints ([`app/main.py`](../app/main.py))

| Endpoint         | Use |
|------------------|-----|
| `/health/live`   | Liveness — process is up. Used by the Docker `HEALTHCHECK`. |
| `/health/ready`  | Readiness — checks DB **and** Redis; returns `not_ready` if either is down. Point your load balancer / orchestrator here. |
| `/health`        | Full status incl. environment and per-service detail. |

### Metrics

- `/metrics` exposes Prometheus metrics.
- **Protected:** requires `Authorization: Bearer $METRICS_TOKEN` when the token
  is set; returns 404 in production if the token is unset.
- Prometheus scrape config: [`prometheus.yml`](../prometheus.yml) — add
  `bearer_token` matching `METRICS_TOKEN` for production scraping.
- Grafana (Compose) on port 3000 for dashboards.

### Tracing

OpenTelemetry is wired into FastAPI, HTTPX, Redis, and SQLAlchemy
([`app/core/tracing.py`](../app/core/tracing.py)); traces export to Jaeger
(UI on port 16686). Disable in tests with `OTEL_SDK_DISABLED=true`.

### Logs

Structured JSON logs with ISO timestamps and request/correlation IDs
([`app/try_except/logging.py`](../app/try_except/logging.py)). Ship container
stdout to your log aggregator (Loki, CloudWatch, ELK, …). Log level follows
`DEBUG`; keep it `false` in production.

---

## Common procedures

### Apply a new migration
```bash
alembic revision --autogenerate -m "describe change"   # review the generated file!
alembic upgrade head
```
Always read the autogenerated migration before applying — autogenerate can miss
or mis-order destructive changes.

### Roll back one migration
```bash
alembic downgrade -1
```

### Rotate the JWT secret
Changing `JWT_SECRET_KEY` invalidates all existing **access** tokens (users must
re-authenticate; refresh tokens are DB-backed and independent). Do this
immediately on any suspected key leak.

### Investigate a failed payment
1. Check `payment_audit_log` for the payment id — every gateway event is recorded.
2. Confirm the reconciliation job is running (it re-checks pending payments every 5m).
3. Refunds only mark `REFUNDED` **after** the gateway confirms; a stuck refund
   raises `ExternalServiceError` and rolls back rather than falsely marking success.

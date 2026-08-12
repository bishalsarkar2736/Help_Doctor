# Deployment Guide

This covers local development, the Docker Compose stack, database migrations,
and going to production. Configuration values are documented separately in
[CONFIGURATION.md](CONFIGURATION.md).

---

## 1. Runtime topology

The application is **not a single process**. A complete deployment runs:

| Process        | Command                                        | Purpose |
|----------------|------------------------------------------------|---------|
| API            | `uvicorn app.main:app --host 0.0.0.0 --port 8000` | HTTP + WebSocket |
| Celery worker  | `celery -A app.core.celery worker`             | Background tasks (push, slot gen, reconciliation, reminders). Concurrency comes from `CELERY_WORKER_CONCURRENCY`, **not** a CLI flag. |
| Celery beat    | `celery -A app.core.celery beat`               | Schedules the periodic tasks |
| Outbox worker  | `python -m app.workers.run_outbox_worker`      | Drains the transactional outbox → downstream effects |

Backing services: **PostgreSQL** and **Redis** (broker + cache + pub/sub).

> **Why beat matters:** appointment reminders, payment reconciliation, and slot
> generation are scheduled by Celery beat (see
> [`app/core/celery.py`](../app/core/celery.py)). If beat isn't running, those
> jobs never fire. Run **exactly one** beat instance — never one per API replica.

---

## 2. Local development (without Docker)

See the [README quick start](../README.md#quick-start-local-without-docker).
Key points:

- Postgres and Redis must be reachable (compose can supply just those:
  `docker compose up -d postgres redis`).
- Migrations run with a **sync** driver — set `DATABASE_URL` with
  `postgresql+psycopg2://…` (Alembic converts `+asyncpg` automatically, but the
  driver must be installed). Then `alembic upgrade head`.
- `uvicorn app.main:app --reload` for hot reload.

---

## 3. Docker Compose

```bash
cp .env.example .env      # fill in real values first
docker compose up --build
```

Services defined in [`docker-compose.yml`](../docker-compose.yml):

| Service          | Port(s)        | Notes |
|------------------|----------------|-------|
| `migrate`        | —              | One-shot `alembic upgrade head`; DB services wait for it to finish. |
| `api`            | 8000           | Non-root user, `HEALTHCHECK` on `/health/live`. |
| `web`            | 5173→80        | Frontend SPA on nginx (built from `../helpdoctor-frontend`). |
| `celery_worker`  | —              | Shares the image; runs the worker. |
| `celery_beat`    | —              | Single scheduler. |
| `postgres`       | 5433→5432      | Named volume `postgres_data`; `pg_isready` healthcheck. |
| `redis`          | 6379           | `redis-cli ping` healthcheck. |
| `db_backup`      | —              | Hourly `pg_dump` into the `db_backups` volume (see OPERATIONS.md). |
| `jaeger`         | 16686 (UI)     | Trace visualization. |
| `prometheus`     | 9090           | Scrapes `/metrics`. |
| `grafana`        | 3000           | Dashboards. |

Notes:
- Uploads and signatures use **named volumes** (`uploads_data`, `media_data`) so
  they survive container recreation. (See the horizontal-scaling caveat below.)
- The API depends on Postgres/Redis being **healthy** before it starts.
- There is intentionally **no `.:/app` bind mount** — the image is immutable.
  For live-reload during development, add a bind mount in a separate
  `docker-compose.override.yml` rather than editing the base file.

### Running migrations in Docker

Migrations run **automatically**: the one-shot `migrate` service applies
`alembic upgrade head` on `docker compose up`, and `api`/`celery_*` wait for it
to finish (`service_completed_successfully`) — so migrations run exactly once and
replicas never race. To run them manually against a running stack:

```bash
docker compose run --rm migrate
```

---

## 4. Production deployment

### 4.1 Build the image

The [`Dockerfile`](../Dockerfile) produces a runtime image that:
- runs as a non-root `app` user,
- includes a `HEALTHCHECK` hitting `/health/live`,
- pre-creates the `media/` and `uploads/` directories.

```bash
docker build -t helpdoctor-api:<version> .
```

The **frontend** has its own multi-stage image
([`helpdoctor-frontend/Dockerfile`](../../helpdoctor-frontend/Dockerfile)) that
builds the SPA and serves it with nginx. `VITE_API_URL` is baked in at build
time, so point it at the public API origin:

```bash
docker build -t helpdoctor-web:<version> \
  --build-arg VITE_API_URL=https://api.example.com ./helpdoctor-frontend
```

### 4.2 Configuration & secrets

- Inject env vars from your platform's **secret manager** — do not ship a `.env`
  into the image. The image contains no secrets.
- Set the production values from the
  [CONFIGURATION.md checklist](CONFIGURATION.md#production-env-checklist).
- **`ALLOWED_HOSTS` must name the hostnames this deployment answers on.** The API
  refuses to start when `ENV=production` and it is still the development default,
  empty, loopback-only, or a wildcard — so a missing value fails at startup with a
  message rather than as every request returning 400 once traffic arrives. Set it
  in the same place as the rest of the environment (the `env_file` compose reads,
  or your platform's secret manager); do **not** rely on exporting it in the
  deploying shell.

### 4.2.1 Production metrics scraping

`METRICS_TOKEN` protects `/metrics` **and locks Prometheus out at the same time**,
so it takes three coordinated steps, not one. Doing only the first leaves the API
serving traffic normally while the `fastapi` target sits DOWN and every alert
built on API metrics — error rates, latency, payment failures, login spikes —
silently has no data behind it.

```bash
# 1. the API side: the token itself, in the env file / secret manager
METRICS_TOKEN=<random secret>

# 2. the scraper side: the SAME value, in a gitignored file (printf, not echo —
#    a trailing newline makes the token wrong)
mkdir -p secrets
printf '%s' "$METRICS_TOKEN" > secrets/metrics_token

#    644, NOT 600. prom/prometheus runs as nobody (65534), so a 0600 file owned
#    by the deploying user is unreadable to it and every scrape fails with
#    "unable to read authorization credentials". 0640 fails for the same reason.
#    On a host with untrusted local users, prefer:
#        chown 65534 secrets/metrics_token && chmod 600 secrets/metrics_token
chmod 644 secrets/metrics_token

# 3. select the config that reads it
PROMETHEUS_CONFIG=./prometheus.production.yml docker compose up -d
```

Verify before deploying — this fails with a non-zero exit if any of the three
disagree:

```bash
python scripts/check_production_env.py .env.production
```

Why a separate config file: `promtool check config` exits 1 when
`bearer_token_file` names a path that does not exist, and the token file is
gitignored and created per host. Putting the directive in the shared
`prometheus.yml` would break that check on every fresh clone and in CI.
`alertmanager.production.yml` exists for the same reason.

After deploying, confirm the target recovered — `health` must be `up`:

```bash
curl -s localhost:9091/api/v1/targets | grep -o '"job":"fastapi".*"health":"[a-z]*"'
```

### 4.2.2 Production alert delivery

Alertmanager reads its SMTP password and Slack webhook from the same mounted
`./secrets` directory, and **runs as `nobody` (uid 65534)**. That combination has
one trap, and it is the same one the metrics token has:

```bash
ALERTMANAGER_CONFIG=./alertmanager.production.yml docker compose up -d

printf '%s' 'your-smtp-password'     > secrets/smtp_password
printf '%s' 'https://hooks.slack...' > secrets/slack_webhook

# 644, NOT 600 — see below
chmod 644 secrets/smtp_password secrets/slack_webhook
```

`chmod 600` owned by the deploying user makes both files unreadable to
Alertmanager, and **nothing reports it**: the container starts, `amtool
check-config` returns SUCCESS, the API answers 200, and Prometheus shows alerts
firing. Delivery fails only at send time:

```
notify retry canceled due to unrecoverable error after 1 attempts:
open /etc/alertmanager/secrets/slack_webhook: permission denied
```

Measured in a throwaway stack: 54 attempts, 54 failures, nothing delivered — for
every rule in `alerts.yml`. Unlike the Prometheus token there is no static
validator that catches it (`promtool` exits 1, `amtool` does not) and no scraped
metric that reveals it, so the deploy gate is the only place it can be caught:

```bash
python scripts/check_production_env.py .env.production
```

That derives the required files from `alertmanager.production.yml` itself, so a
receiver added later with a new credential is covered automatically. On a host
with untrusted local users, `chown 65534 secrets/* && chmod 600 secrets/*` is
accepted too.

### 4.2.3 The dead-man's switch (external heartbeat)

Every alert rule in `alerts.yml` is evaluated **by Prometheus**. If Prometheus
stops — crashed, OOM-killed, host rebooted and the container never came back,
network partitioned — all of them stop evaluating at the same instant and the
system goes completely silent. Silence looks exactly like health. Nothing inside
this Docker host can detect that, because anything inside it dies with it.

The `Watchdog` alert inverts the signal: it fires permanently and is delivered
every minute to an external monitor, which raises the alarm when the heartbeat
**stops arriving**.

**The receiving service must live outside this Docker host — outside this
machine.** A monitor running here would die in exactly the scenarios it exists to
report. This project uses [Healthchecks.io](https://healthchecks.io); any
heartbeat/cron-monitoring service works, provided it alerts on *absence*.

**Production provisioning happens at deployment time, not now.** The repository
carries the rule, the routing and the tests; it deliberately contains no account,
no check and no URL.

When you are ready to deploy:

```bash
# 1. Create a check on the external service. Set its period to 1 minute and its
#    grace period to ~5 minutes — the routing pings every minute, so ~5 minutes
#    tolerates a few missed pings without a false alarm.

# 2. Put the ping URL on the deploy host. It is a CREDENTIAL: anyone holding it
#    can ping the monitor and silence your alarm.
printf '%s' 'https://hc-ping.com/<your-uuid>' > secrets/watchdog_url

# 3. 644, not 600 — Alertmanager runs as uid 65534 (see §4.2.2).
chmod 644 secrets/watchdog_url

# 4. The deploy gate refuses to proceed without it.
python scripts/check_production_env.py .env.production
```

`secrets/` is gitignored and `scripts/check_production_env.py` derives this file
from `alertmanager.production.yml` automatically — it requires the file to exist,
to be a regular file, and to be readable by Alertmanager, the same as the SMTP
password and Slack webhook.

**Verify after deploying.** The switch is only real once the external service has
seen a ping:

```bash
# Alertmanager should show the watchdog delivering, with no failures
curl -s localhost:9093/metrics | grep '^alertmanager_notifications_total{integration="webhook"}'
curl -s localhost:9093/metrics | grep '^alertmanager_notifications_failed_total' | awk '$2 != 0'
```

Then confirm the check has turned green on the external dashboard, and — the
part people skip — **stop Alertmanager and confirm the external monitor alarms.**
An untested dead-man's switch is indistinguishable from a working one right up
until the day it matters.

Two properties worth keeping in mind:

* The `Watchdog` alert fires forever and appears permanently in the Alertmanager
  UI. That is intended. It is routed to its own receiver with no email or chat
  integration, so it never pages a human; a page arriving every minute is how
  people learn to ignore pages.
* It detects "Prometheus/Alertmanager stopped, or the host or its network is
  gone". It does **not** detect a Prometheus that runs but evaluates wrongly, and
  the heartbeat can keep flowing while one specific receiver is broken —
  `AlertmanagerNotificationsFailing` covers that case.

### 4.3 Database

- Provision managed Postgres (or a hardened self-managed instance).
- Run `alembic upgrade head` as part of the release, **before** the new API
  version serves traffic.
- Set up backups — see [OPERATIONS.md § Backups](OPERATIONS.md#backups).

### 4.4 TLS and reverse proxy (not yet included)

The app serves plain HTTP on port 8000. **You must terminate TLS in front of
it.** Two common paths:

- **Managed platform** (Render / Fly / Railway / an ALB / etc.) — the platform
  terminates HTTPS; point it at the container's port 8000. Nothing to add here.
- **Self-managed VPS** — put Nginx (or Caddy/Traefik) in front, terminate TLS
  with Let's Encrypt, and proxy to the API. WebSocket upgrade headers must be
  forwarded (`Upgrade`/`Connection`) for the realtime endpoints to work.

The **frontend** image already runs nginx
([`helpdoctor-frontend/nginx.conf`](../../helpdoctor-frontend/nginx.conf)),
serving the SPA on port 80 (SPA fallback, gzip, asset caching, security
headers). For TLS on that image, either terminate upstream (LB/ingress) or add a
`listen 443 ssl;` block with `ssl_certificate`/`ssl_certificate_key` pointing at
mounted certs plus an HTTP→HTTPS redirect. The API (no `/api` prefix) is a
**separate origin** — set `VITE_API_URL` to its public URL at build time and add
that origin to the API's `ALLOWED_ORIGINS`.

### 4.5 Horizontal scaling caveats

- **API** scales horizontally freely *up to the*
  [connection budget](CONFIGURATION.md#connection-budget) — each replica adds
  a full DB pool. Run **one** Celery beat regardless of API replica count.
- **Local-disk uploads:** clinic logos and doctor signatures are written to
  local paths (`uploads/`, `media/`). With multiple API replicas behind a load
  balancer, a file written by one replica isn't visible to the others. Before
  scaling the API past one instance, move these to shared object storage (e.g.
  S3-compatible) or a shared network volume. This is a **known limitation**.

---

## 5. Production checklist

**Done in this codebase**

- [x] Docker image runs as non-root, with a healthcheck
- [x] Compose stack with healthchecks, named volumes, Celery worker+beat, hourly backups
- [x] Health endpoints (`/health`, `/health/live`, `/health/ready`)
- [x] Prometheus metrics (token-protected) + OpenTelemetry tracing
- [x] Structured JSON logging with request/correlation IDs
- [x] CORS driven by `ALLOWED_ORIGINS`; security headers middleware
- [x] Secrets removed from source; `DEBUG`-in-prod guard active
- [x] Rate limiting on auth, payment webhook, and AI endpoints
- [x] File upload validation (size, magic bytes, and full image decode)
- [x] CI: automated tests + lint on every push/PR
- [x] Automated DB backup script + scheduled backup service

**You must do (host-dependent or operational)**

- [ ] TLS termination / reverse proxy (§4.4)
- [ ] Deploy pipeline for your chosen host (image build/push + release)
- [ ] Rotate all dev secrets before go-live (JWT, DB, VAPID, mail)
- [ ] Move uploads to shared storage before scaling the API past one replica (§4.5)
- [ ] Verify a backup **restore** actually works (OPERATIONS.md)
- [ ] Check the [connection budget](CONFIGURATION.md#connection-budget) against
      your Postgres `max_connections` before adding API replicas or raising
      `CELERY_WORKER_CONCURRENCY` — exhausting it refuses connections outright.

**Deliberate product/compliance decisions**

- [x] Medical and financial records survive account deletion: users are
      soft-deleted and the FKs are `RESTRICT`, so the database refuses a hard
      delete. See [SECURITY.md](SECURITY.md#compliance-considerations-decide-deliberately).
- [ ] No **retention window** — nothing is ever purged. Set one if your
      jurisdiction requires it.
- [ ] No **anonymisation path** for GDPR right-to-erasure (scrub identity,
      keep clinical rows). Needs a jurisdiction decision first.
- [ ] PHI fields are stored relying on DB/disk-level protection (no app-level
      field encryption) — confirm this meets your regulatory bar.

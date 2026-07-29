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

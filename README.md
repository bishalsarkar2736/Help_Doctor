# 🏥 Help_Doctor — Backend API

Help_Doctor is a multi-tenant clinic management backend: appointments, doctors,
patients, prescriptions, payments (bKash / Nagad / Rocket), notifications
(email / web-push / realtime), and an optional AI medicine assistant.

Built with **FastAPI**, **async SQLAlchemy**, **PostgreSQL**, **Redis**, and
**Celery**, with **Alembic** migrations and a **pytest** suite (212 tests).

---

## Tech stack

| Concern            | Choice                                             |
|--------------------|----------------------------------------------------|
| Language / runtime | Python 3.12                                        |
| Web framework      | FastAPI + Uvicorn                                  |
| ORM / DB           | SQLAlchemy 2 (async, asyncpg) + PostgreSQL 16      |
| Migrations         | Alembic                                            |
| Cache / broker     | Redis 7                                            |
| Background jobs    | Celery worker + Celery beat                        |
| Realtime           | WebSockets + Redis pub/sub                         |
| Observability      | OpenTelemetry (Jaeger) + Prometheus + JSON logs    |
| Auth               | JWT (access) + opaque rotating refresh tokens, Google OAuth |
| Tests / lint       | pytest, pytest-asyncio, ruff                       |

---

## Documentation

| Doc | What's in it |
|-----|--------------|
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Every environment variable, with defaults and prod guidance |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)       | Local dev, Docker Compose, production deploy, migrations, TLS |
| [docs/OPERATIONS.md](docs/OPERATIONS.md)       | Backups, Celery, monitoring, health checks, runbook |
| [docs/SECURITY.md](docs/SECURITY.md)           | Auth model, RBAC, headers, secrets, hardening checklist |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)   | Domain model, entity ownership, appointment lifecycle (frozen rules) |

---

## Quick start (local, without Docker)

```bash
# 1. Clone and enter
git clone <your-repo-url> Help_Doctor
cd Help_Doctor

# 2. Virtualenv + deps
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt          # add -dev for ruff: requirements-dev.txt

# 3. Configure
cp .env.example .env                      # then fill in the values (see docs/CONFIGURATION.md)

# 4. Bring up Postgres + Redis (or use your own)
docker compose up -d postgres redis

# 5. Run migrations
export DATABASE_URL="postgresql+psycopg2://<user>:<pass>@localhost:5432/<db>"
alembic upgrade head

# 6. Start the API
uvicorn app.main:app --reload
```

- API: <http://127.0.0.1:8000>
- Swagger UI: <http://127.0.0.1:8000/docs>
- Health: <http://127.0.0.1:8000/health>

To run the periodic jobs locally you also need the Celery processes:

```bash
celery -A app.core.celery worker --loglevel=info
celery -A app.core.celery beat   --loglevel=info
```

---

## Quick start (Docker Compose)

```bash
cp .env.example .env      # fill in values
docker compose up --build
```

This starts: API, Celery worker, Celery beat, Postgres, Redis, hourly DB backup,
Jaeger, Prometheus, and Grafana. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

---

## Running tests & lint

```bash
source venv/bin/activate
python -m pytest -q          # requires a reachable test Postgres (see tests/conftest.py)
ruff check .                 # lint
ruff format --check .        # formatting (advisory today; see docs)
```

CI runs both on every push / PR — see [.github/workflows/ci.yml](.github/workflows/ci.yml).

---

## Project layout

```
app/
├── api/routes/        # HTTP endpoints (thin — orchestration only)
├── services/          # business logic (~100 services)
├── domain/            # FSM + scheduling rules (appointment lifecycle, slots)
├── models/            # SQLAlchemy models
├── schemas/           # Pydantic request/response models
├── security/          # JWT, RBAC, Google OAuth
├── core/              # celery, metrics, tracing, cache, limiter
├── task/              # Celery tasks (reminders, reconciliation, slots, push)
├── workers/           # outbox event worker
├── websocket/         # realtime channels + Redis listener
├── integrations/      # bKash / Nagad / Rocket / AI providers
├── try_except/        # exceptions, logging, middleware, audit (cross-cutting)
└── main.py            # app factory, middleware, health/metrics endpoints
alembic/               # migrations
scripts/               # backup_db.sh, seeds, maintenance
docs/                  # this documentation set
tests/                 # pytest suite
```

---

## Production readiness

This backend has had a production-hardening pass. What is done and what still
depends on your hosting decisions is tracked in
[docs/DEPLOYMENT.md § Production checklist](docs/DEPLOYMENT.md#production-checklist)
and [docs/SECURITY.md](docs/SECURITY.md).

# Configuration Reference

All configuration is loaded from environment variables (or a local `.env` file)
by [`app/config.py`](../app/config.py) using `pydantic-settings`. Unknown keys
are **rejected** (`extra="forbid"`), so a typo in `.env` will fail fast at
startup rather than being silently ignored.

Two settings are validated at load time:

- **`JWT_SECRET_KEY`** must be at least 32 characters.
- **`DEBUG`** cannot be `true` when `ENV=production` (raises at startup).

Copy [`.env.example`](../.env.example) to `.env` as a starting point.

---

## Application

| Variable    | Required | Default       | Notes |
|-------------|----------|---------------|-------|
| `APP_NAME`  | no       | `HelpDoctor`  | Shown in health responses and OpenAPI title. |
| `ENV`       | no       | `development` | One of `development`, `staging`, `production`. Gates prod-only behavior. |
| `DEBUG`     | no       | `false`       | Enables SQL echo + FastAPI debug. **Must be `false` in production.** |
| `ALLOWED_HOSTS` | **in production** | `localhost,127.0.0.1,testserver` | Comma-separated hostnames this deployment answers on. The app **refuses to start** when `ENV=production` and this is still the default, empty, loopback-only, or contains a wildcard. Literal hostnames only — the `Host` header is compared by equality, so `*` and `*.example.com` match nothing and reject everything. Ports are ignored. `localhost` and `127.0.0.1` are always accepted and need not be listed. |

## PostgreSQL

| Variable            | Required | Default | Notes |
|---------------------|----------|---------|-------|
| `POSTGRES_HOST`     | **yes**  | —       | Hostname. In Docker Compose this is the service name `postgres`. |
| `POSTGRES_PORT`     | no       | `5432`  | |
| `POSTGRES_DB`       | **yes**  | —       | |
| `POSTGRES_USER`     | **yes**  | —       | |
| `POSTGRES_PASSWORD` | **yes**  | —       | URL-encoded automatically for the connection string. |
| `DB_POOL_SIZE`      | no       | `5`     | Pooled connections **per process**. See the budget below. |
| `DB_MAX_OVERFLOW`   | no       | `10`    | Extra connections above the pool under burst, **per process**. |

The async connection URL is built from these (`database_url` property). The
engine also sets `pool_pre_ping=True, pool_recycle=1800` — see
[`app/db/postgres.py`](../app/db/postgres.py).

### Connection budget

The pool is **per process**, and every process that touches the database opens
its own — including each Celery prefork child. The ceiling is therefore:

```
(api processes + celery children + beat) x (DB_POOL_SIZE + DB_MAX_OVERFLOW)
```

That total must stay below the server's `max_connections`. Postgres does not
degrade when it runs out — it refuses new connections outright, which takes the
API down with it.

With the defaults, against a stock `max_connections = 100`:

| Process | Count | Per process | Total |
|---------|-------|-------------|-------|
| api     | 1     | 15          | 15    |
| celery  | 4     | 15          | 60    |
| beat    | 1     | 15          | 15    |
| **Ceiling** | | | **90** (of ~97 usable, after superuser reserve) |

Consequences worth knowing before you tune anything:

- **`CELERY_WORKER_CONCURRENCY` is a multiplier on this budget.** Raising it
  without raising `max_connections` is the easiest way to exhaust the server.
- **Running more than one API replica multiplies it too.** Two replicas with
  the defaults is +15.
- Past roughly one replica and a handful of workers, put **pgbouncer** in front
  rather than continuing to grow `max_connections`.

Check what a running system actually holds:

```sql
SELECT state, count(*) FROM pg_stat_activity
WHERE datname = 'helpdoctor_db' GROUP BY state;
```

## Redis

| Variable     | Required | Default                    | Notes |
|--------------|----------|----------------------------|-------|
| `REDIS_URL`  | no       | `redis://localhost:6379/0` | Used as the Celery broker/backend, cache, and pub/sub. |
| `REDIS_HOST` | no       | `localhost`                | |
| `REDIS_PORT` | no       | `6379`                     | |

## Celery

| Variable                     | Required | Default | Notes |
|------------------------------|----------|---------|-------|
| `CELERY_WORKER_CONCURRENCY`  | no       | `4`     | Prefork children per worker. **Multiplies the [connection budget](#connection-budget).** |

Set in [`app/core/celery.py`](../app/core/celery.py) as `worker_concurrency`,
deliberately **not** as a `--concurrency` CLI flag, so the bound holds however
the worker is started. Do not add the flag back: it overrides the config and
reintroduces two places to keep in sync.

Left unset, Celery forks **one child per CPU**. On a 16-core host that is 16
children each holding a full DB pool — far past what Postgres will accept. The
workload here is I/O-bound (email, push, reconciliation), so extra children buy
little throughput while multiplying connections.

## Auth / JWT

| Variable                      | Required | Default | Notes |
|-------------------------------|----------|---------|-------|
| `JWT_SECRET_KEY`              | **yes**  | —       | **≥ 32 chars.** Signs access tokens. Rotate on any suspected leak. |
| `ALGORITHM`                  | no       | `HS256` | JWT signing algorithm. |
| `ACCESS_TOKEN_EXPIRE_MINUTES`| no       | `60`    | Access-token lifetime. |
| `REFRESH_TOKEN_EXPIRE_DAYS`  | no       | `7`     | Refresh-token lifetime (opaque, DB-backed, rotated). |
| `GOOGLE_CLIENT_ID`           | **yes**  | —       | Google OAuth. |
| `GOOGLE_CLIENT_SECRET`       | **yes**  | —       | Google OAuth. |

## CORS & metrics

| Variable          | Required | Default                 | Notes |
|-------------------|----------|-------------------------|-------|
| `FRONTEND_URL`    | no       | `http://localhost:5173` | Reference to your SPA origin. |
| `ALLOWED_ORIGINS` | no       | `http://localhost:5173` | **Comma-separated** list of allowed CORS origins. Set this to your real frontend origin(s) in production. |
| `METRICS_TOKEN`   | no       | _unset_                 | If set, `/metrics` requires `Authorization: Bearer <token>`. If unset **and** `ENV=production`, `/metrics` returns 404. Always set it in prod. |

## Email (SMTP)

| Variable        | Required | Default | Notes |
|-----------------|----------|---------|-------|
| `MAIL_HOST`     | **yes**  | —       | |
| `MAIL_PORT`     | no       | `587`   | |
| `MAIL_USERNAME` | **yes**  | —       | |
| `MAIL_PASSWORD` | **yes**  | —       | Use an app-password / API credential, not a human login. |
| `MAIL_FROM`     | **yes**  | —       | Must be a valid email address. |
| `MAIL_USE_TLS`  | no       | `true`  | |

## Web push (VAPID) — optional

| Variable            | Required | Default | Notes |
|---------------------|----------|---------|-------|
| `VAPID_PUBLIC_KEY`  | no       | _unset_ | Required only if web-push notifications are enabled. |
| `VAPID_PRIVATE_KEY` | no       | _unset_ | |
| `VAPID_EMAIL`       | no       | _unset_ | `mailto:` contact for push services. |

## Payment gateways

All fields are required (the app fails to start without them). Card data is
never stored — only gateway references. See [docs/SECURITY.md](SECURITY.md).

**bKash**

| Variable             | Notes |
|----------------------|-------|
| `BKASH_BASE_URL`     | Gateway base URL (sandbox vs production differ). |
| `BKASH_APP_KEY`      | |
| `BKASH_APP_SECRET`   | |
| `BKASH_USERNAME`     | |
| `BKASH_PASSWORD`     | |
| `BKASH_CALLBACK_URL` | Public URL bKash redirects to after payment. |

**Nagad**

`NAGAD_BASE_URL`, `NAGAD_MERCHANT_ID`, `NAGAD_PUBLIC_KEY`, `NAGAD_PRIVATE_KEY`,
`NAGAD_CALLBACK_URL`.

**Rocket**

`ROCKET_BASE_URL`, `ROCKET_MERCHANT_ID`, `ROCKET_API_KEY`, `ROCKET_CALLBACK_URL`.

## Other integrations

| Variable                   | Required | Default         | Notes |
|----------------------------|----------|-----------------|-------|
| `WHATSAPP_ACCESS_TOKEN`    | **yes**  | —               | WhatsApp Business API. |
| `WHATSAPP_PHONE_NUMBER_ID` | **yes**  | —               | |
| `ELASTIC_HOST`             | no       | `http://localhost:9200` | |
| `BASE_URL`                 | **yes**  | —               | Public base URL of this API (used for QR verification links). |

## AI medicine assistant — optional

| Variable             | Required | Default        | Notes |
|----------------------|----------|----------------|-------|
| `ENABLE_MEDICINE_AI` | no       | `false`        | Master switch for the AI assistant feature. |
| `AI_PROVIDER`        | no       | `openai`       | One of `openai`, `anthropic`, `gemini`. |
| `OPENAI_API_KEY`     | no       | _unset_        | Required if `AI_PROVIDER=openai` and the feature is enabled. |
| `OPENAI_MODEL`       | no       | `gpt-4.1-mini` | |

> The `/medicines/*` endpoints require authentication, and `/medicines/assistant`
> is rate-limited (10/min). Keep `ENABLE_MEDICINE_AI=false` until you intend to
> pay for the provider.

---

## Production `.env` checklist

- [ ] `ENV=production`, `DEBUG=false`
- [ ] `JWT_SECRET_KEY` is a fresh random ≥32-char value (not the dev one)
- [ ] `POSTGRES_PASSWORD` rotated from any value that ever lived in git/dev
- [ ] `ALLOWED_HOSTS` set to your real hostname(s), comma-separated (the app refuses to start otherwise — see Application above)
- [ ] `ALLOWED_ORIGINS` set to your real frontend origin(s), comma-separated
- [ ] `METRICS_TOKEN` set to a random secret, **and** the same value written to `secrets/metrics_token`, **and** deployed with `PROMETHEUS_CONFIG=./prometheus.production.yml` — setting only the first locks Prometheus out and every API alert silently loses its data
- [ ] `BASE_URL` and all `*_CALLBACK_URL`s point to your real HTTPS domain
- [ ] Payment gateways pointed at **production** (not sandbox) URLs & credentials
- [ ] `MAIL_*` uses a real transactional-email credential
- [ ] Secrets injected from a secret manager, not a committed file

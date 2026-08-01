# Staging

A second, isolated instance of the whole stack on the same host, for validating
**deployment and operations** before promoting a change — not for feature work.

It answers the questions production cannot afford to answer for the first time:
does this commit migrate cleanly, do the services come up in a working order,
does the nginx-to-api seam hold, can a real account authenticate through the
browser path, and can a brand new deployment be bootstrapped at all.

```bash
scripts/staging.sh up      # build, start, wait for health, run migrations
scripts/staging.sh seed    # bootstrap super admin + first clinic + accounts
scripts/staging.sh smoke   # 18 operational checks; exit 1 blocks promotion
scripts/staging.sh status
scripts/staging.sh logs [service]
scripts/staging.sh down    # stop and DELETE staging volumes
```

## Isolation

| | production | staging |
|---|---|---|
| compose project | `help_doctor` | `helpdoctor_staging` |
| containers | `helpdoctor_*` | `staging_*` |
| api / web | 8000 / 5173 | 18000 / 15173 |
| postgres / redis | 5433 / 6379 | 15433 / 16379 |
| minio | 9101 / 9102 | 19101 / 19102 |
| env file | `.env.docker` | `.env.staging` (generated) |
| volumes | `help_doctor_*` | `helpdoctor_staging_*` |

Everything binds to `127.0.0.1`. Both stacks run at once; verified with 14
production and 8 staging containers up simultaneously and production serving
normally throughout.

**Secrets are generated, never copied.** Staging is the less guarded
environment by definition — test data, wider access, more experimentation — so
sharing a JWT key or database password with production would make a staging
compromise a production one. `.env.staging` and `.env.staging`-derived files are
gitignored.

## Three compose traps, all found the hard way here

Compose **merges** list fields across `-f` files instead of replacing them, and
`container_name` is global rather than project-scoped. A second instance
therefore cannot run without explicit overrides:

* **`container_name`** — collides before it ever reaches a port.
* **`ports`** — a plain `ports:` *appends*, so the original host port is still
  published. The first attempt collided on 3000. `!override` is what makes a
  replacement actually replace.
* **`env_file`** — the same rule with a much nastier failure. Appending
  `.env.staging` to `.env.docker` means every key present in production's file
  but **absent** from staging's silently keeps its production value.

That last one is worth dwelling on. `.env.docker` defines `DATABASE_URL`;
`.env.example` does not, so the generated staging file never overrode it — and
`alembic/env.py` prefers `DATABASE_URL` over the application settings. Staging's
migrate container connected to the **staging** database using the **production**
password and failed authentication, while every other container used the right
one. The symptom (auth failure) pointed nowhere near the cause (a merged env
file). `env_file: !override [.env.staging]` fixes it.

## The day-one bootstrap

`scripts/staging.sh seed` deliberately follows the real path rather than
inserting rows:

1. `scripts/create_super_admin.py` creates the platform super admin
2. `scripts/staging_bootstrap_clinic.py` logs in as that admin and creates the
   first clinic **through the API**
3. `scripts/seed_e2e_accounts.py` seeds the per-role test accounts

This is how a brand new production deployment has to be brought into service,
and nothing had ever exercised it end to end — the seeder simply stops with
"No clinic exists. Bootstrap one before seeding." Doing it on staging first
means a failure is found with no users waiting, rather than on the day you go
live with no way in.

`seed_e2e_accounts.py` refuses to run unless `ENV` is development, testing or
staging. Staging was added to that list deliberately: it is disposable,
loopback-only, and never holds real patients. **Production is still refused**,
and that list is the one place to check if the assumption ever stops holding.

## What smoke validates

18 checks, each corresponding to something that has actually broken in this
project at least once:

* api liveness, readiness, and each dependency (database, redis) individually
* the SPA is served, and the API is reachable **through the proxy** — the seam
  where a cached nginx upstream IP once took the frontend down while both
  containers reported healthy
* CSP is served and does not allow `connect-src *`
* login through the proxy, the refresh token is **not** in the response body,
  and its cookie is `HttpOnly` + `SameSite=Strict`
* an authenticated request succeeds and an unauthenticated one is refused
* metrics are exported and no raw ids appear in metric path labels (the
  cardinality guard)

Exit code is 0 only if every check passes, so it works as a promotion gate:

```bash
scripts/staging.sh up && scripts/staging.sh seed && scripts/staging.sh smoke \
  && echo "safe to promote"
```

## Not included

The observability stack (prometheus, grafana, jaeger, alertmanager) and the
backup loops are not started by default — they double the container count on a
single machine for little deployment-validation value. Their names and ports are
still overridden in `docker-compose.staging.yml`, so adding them to `SERVICES`
in `scripts/staging.sh` works without collisions.

Staging is **not** a performance environment. It shares a host with production,
so timings there say nothing useful about production latency.

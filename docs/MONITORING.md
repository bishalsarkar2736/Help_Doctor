# Monitoring and alerting

## What was broken

Prometheus, Grafana and Jaeger had been running for weeks and were collecting
**nothing from the application**. Three independent faults, each invisible on
its own — the dashboards looked fine because there was no data to contradict
them:

1. **Wrong scrape target.** `prometheus.yml` pointed at `localhost:8000`, but
   inside the Prometheus container `localhost` is Prometheus. The `fastapi`
   target sat permanently `DOWN` with `connection refused`.
2. **`alerts.yml` was a directory.** Compose bind-mounted `./alerts.yml`; the
   file did not exist, so Docker created a directory of that name. Prometheus
   reported zero rule groups. `rule_files` also pointed at a third path
   (`monitoring/alerts.yml`) that never existed.
3. **No Alertmanager.** `activeAlertmanagers: []`. Even with rules loaded,
   nothing would ever notify a human.

The lesson worth keeping: **a missing bind-mount source becomes a directory,
silently.** If a mounted config file "isn't being read", check whether Docker
turned it into a folder.

## How to verify it is actually working

Never trust the Grafana UI for this — it renders happily with no data.

**Prometheus and Alertmanager only re-read their configuration on reload.**
`prometheus.yml`, `alerts.yml` and `alertmanager.yml` are bind-mounted read-only,
so editing them changes nothing until the process reloads. If the checks below
show fewer targets or rule groups than the files declare, that is what happened —
the running instance is still on the previous configuration, not broken.

```bash
# 1. All five targets must be "up": fastapi, celery, outbox_worker,
#    alertmanager, prometheus
curl -s localhost:9091/api/v1/targets | jq '.data.activeTargets[] | {job:.labels.job, health}'

# 2. All eight rule groups must be loaded (groups must not be [])
curl -s localhost:9091/api/v1/rules | jq '.data.groups[].name'

# 3. Alertmanager must be discovered (must not be [])
curl -s localhost:9091/api/v1/alertmanagers | jq '.data.activeAlertmanagers'

# 4. Real data must be queryable. Use a metric that always exists — a labelled
#    counter like login_attempts_total returns nothing until someone logs in,
#    which looks identical to a broken scrape.
curl -s --get localhost:9091/api/v1/query --data-urlencode 'query=up'
curl -s --get localhost:9091/api/v1/query --data-urlencode 'query=http_requests_total'

# 5. Worker metrics must arrive from their own processes, not the API
curl -s --get localhost:9091/api/v1/query --data-urlencode 'query=celery_worker_up'
curl -s --get localhost:9091/api/v1/query --data-urlencode 'query=outbox_worker_heartbeat'

# 6. Alerts must reach Alertmanager, not just fire in Prometheus
curl -s localhost:9093/api/v2/alerts | jq '.[].labels.alertname'

# 7. And Alertmanager must have DELIVERED them. Non-zero failures here mean
#    every alert in the system is going nowhere.
curl -s localhost:9093/metrics | grep '^alertmanager_notifications_failed_total' | awk '$2 != 0'
```

## The alert rules

24 rules in 9 groups, in [`alerts.yml`](../alerts.yml). Every rule should be
something a human would act on; alerts that fire on noise train people to ignore
the ones that matter.

**availability**

| alert | severity | why |
|---|---|---|
| `APIDown` | critical | `up == 0`, synthesised by Prometheus, so it fires even when the app is too broken to report anything |
| `APIMetricsUnscrapeable` | warning | target unreachable for 10min — usually `METRICS_TOKEN` misconfigured |

**errors**

| alert | severity | why |
|---|---|---|
| `HighServerErrorRate` | critical | over 1% of requests returning 5xx |
| `EndpointServerErrors` | warning | one endpoint is failing while the overall rate still looks acceptable |
| `PaymentEndpointErrors` | critical | 5xx on the payment routes — money and bookings are being lost |
| `NoTrafficReceived` | warning | no **application** traffic for 15min. Excludes `/metrics`, `/health*` and unrouted requests, or Prometheus's own scrapes would keep it silent forever |

**background_jobs**

| alert | severity | why |
|---|---|---|
| `CeleryWorkerDown` | critical | no worker running: reminders, notifications and scheduled jobs all stop |
| `OutboxWorkerDown` | critical | the dispatcher between publishing an event and anything happening because of it |
| `OutboxWorkerStalled` | critical | process alive but the poll loop stopped — worse than down, because it looks healthy |
| `CeleryWorkerNotExecuting` | critical | worker alive and executing nothing; the descriptor-limit failure looked exactly like this |
| `CeleryBeatNotDispatching` | warning | beat has no healthcheck of its own; this infers it from the absence of dispatched work |
| `CeleryTaskFailures` | warning | a specific task is failing repeatedly |
| `CeleryQueueBacklog` | warning | work arriving faster than it is consumed |
| `CeleryTasksSlow` | warning | p95 above 5min — usually a task waiting on something that will not answer |

**latency**

| alert | severity | why |
|---|---|---|
| `HighAPILatency` | warning | p95 > 1s for 10min |

**security**

| alert | severity | why |
|---|---|---|
| `LoginFailureSpike` | warning | brute force / credential stuffing |
| `LoginFailureMajority` | warning | >80% of logins failing — attack, or auth is broken |

**money**

| alert | severity | why |
|---|---|---|
| `PaymentFailures` | critical | money lost and the patient loses their booking |

**data**

| alert | severity | why |
|---|---|---|
| `DatabaseRetries` | warning | deadlocks or connection saturation; usually precedes an outage |
| `DoubleBookingContention` | warning | the guard is working, but firing this often means the UI offers taken slots |

**alerting_pipeline** — the rules that watch the alerting system itself

| alert | severity | why |
|---|---|---|
| `AlertmanagerNotificationsFailing` | critical | alerts fire, Alertmanager accepts them, and delivery fails. Measured on this deployment before the rule existed: 10 attempts, 10 failures, including `CeleryWorkerDown` and `OutboxWorkerDown` |
| `AlertmanagerDown` | critical | rules still evaluate, but nothing routes or delivers. Also fires via `absent()` if the scrape job disappears, since a missing job would otherwise silence this rule |
| `AlertmanagerConfigReloadFailed` | warning | a rejected reload keeps the previous config running, so the deploy looks successful and the change did not happen |

> **The limit of the last group.** An alert about broken delivery is delivered by
> the thing it reports broken. These rules make the failure visible in the
> Prometheus UI, in Grafana and in the firing history — where it was invisible —
> but they cannot page through a path that is down. That is what the `watchdog`
> group below is for.

**watchdog** — the dead-man's switch

| alert | severity | why |
|---|---|---|
| `Watchdog` | watchdog | always firing, on purpose. Delivered continuously to an external monitor that alarms when the stream **stops** |

Rule behaviour is unit-tested with `promtool` in
[`tests/monitoring/alerts_test.yml`](../tests/monitoring/alerts_test.yml) — these
assert that a rule *fires* at its threshold, not merely that it parses.

## Metrics are PER PROCESS — this shapes how they are collected

`prometheus_client` counters live in the process that increments them, so a
metric is only visible where it is produced. This used to mean Celery and outbox
metrics were uncollectable — the API's `/metrics` reported `0` for all of them
and always would. **That gap is closed:** each process now exposes its own
endpoint and has its own scrape job.

| job | target | what it carries |
|---|---|---|
| `fastapi` | `api:8000` | `http_requests_total`, `api_request_latency_seconds`, `login_attempts_total`, `payments_*`, `db_retry_total` |
| `celery` | `celery_worker:9100` | `celery_worker_up`, `celery_tasks_total`, `celery_queue_length`, `celery_task_duration_seconds` |
| `outbox_worker` | `outbox_worker:9103` | `outbox_worker_heartbeat`, `outbox_events_processed_total`, `outbox_*` |
| `alertmanager` | `alertmanager:9093` | `alertmanager_notifications_*`, `alertmanager_config_last_reload_successful` |
| `prometheus` | `localhost:9090` | Prometheus's own `up`, `process_*` and `prometheus_notifications_*` |

Two consequences of the per-process model that still bite:

* **Celery prefork needs multiprocess mode.** Task signals fire in the pool
  CHILDREN while the metrics server runs in the parent, so `celery_worker` sets
  `PROMETHEUS_MULTIPROC_DIR` and mounts a tmpfs for it. Without that every
  counter would export zero and a dead worker would look identical to an idle
  one.
* **More than one uvicorn worker** means each process keeps its own counters and
  a scrape hits whichever answers, so counters appear to jump around. Use
  multiprocess mode or one worker per container.

Sending alerts to Alertmanager and scraping Alertmanager are different things:
`alerting.alertmanagers` in `prometheus.yml` is the former and says nothing about
whether delivery succeeded. Both are configured.

## Known instrumentation gaps

Verified against the running stack; the two that used to head this list —
no status-code metric and no Celery scraping — are closed.

* **`api_request_latency_seconds` carries no route label.** Its only labels are
  `le`, `job` and `instance`, so `HighAPILatency` can say the API is slow but not
  which endpoint is. `http_requests_total` *does* carry `method`, `path` and
  `status`, so error rates are attributable per route even though latency is not.
* **No Postgres or Redis exporter**, so connection saturation, replication lag
  and eviction rates are invisible.
* **The dead-man's switch needs an external endpoint before it protects
  anything.** The `Watchdog` rule and its routing are in the repository; the
  Healthchecks.io check that receives it is provisioned at deployment time (see
  below). Until `secrets/watchdog_url` exists on the deploy host, the switch is
  wired but not armed — production deploys are blocked on it by
  `scripts/check_production_env.py`.
* **`login_attempts_total` and `db_retry_total` have no series until first use.**
  They are labelled counters, so their children only exist after a login attempt
  or a retry. An empty query result means "has not happened yet", not "not
  instrumented" — do not use them to check that scraping works.

## Production checklist

* `/metrics` is protected: `app/main.py` requires `Authorization: Bearer
  $METRICS_TOKEN` when set, and returns **404** when `ENV=production` and it is
  **not** set. So switching `ENV` to production without configuring this stops
  scraping dead. Set `METRICS_TOKEN`, write the same value to
  `secrets/metrics_token`, and deploy with
  `PROMETHEUS_CONFIG=./prometheus.production.yml` — that config reads the token
  through `bearer_token_file`, never a literal `bearer_token`, since
  `prometheus.yml` is committed. `python scripts/check_production_env.py
  .env.production` verifies all three and fails the deploy if they disagree.
* Replace the Alertmanager receivers in `alertmanager.yml`. They deliver by SMTP
  to the local MailHog container, so the path is real and testable in
  development — the message lands in the MailHog UI on `:8025` — but reaches
  nobody in production. Put SMTP/Slack credentials in a mounted secret file, not
  inline, and deploy with
  `ALERTMANAGER_CONFIG=./alertmanager.production.yml`.
  Two development-only settings there that must **not** be copied to production
  and must not be "hardened" in development: `smtp_require_tls: false`, because
  MailHog advertises no STARTTLS, and no SMTP credentials at all, because Go's
  SMTP client refuses PLAIN auth over an unencrypted connection. Measured: 0
  messages delivered with either of those changed.
* **Those secret files must be readable by uid 65534.** Alertmanager runs as
  `nobody`, so `chmod 600 secrets/*` owned by the deploying user locks it out —
  and nothing tells you: the container starts, `amtool check-config` returns
  SUCCESS, alerts show as firing, and every notification dies at send time with
  `permission denied`. Measured: 54 attempts, 54 failures, nothing delivered.
  Use `chmod 644 secrets/*`, or `chown 65534 secrets/* && chmod 600 secrets/*`
  on a host with untrusted local users. `scripts/check_production_env.py`
  derives the required files from `alertmanager.production.yml` and fails the
  deploy if any of them is missing or unreadable.
* Prometheus is published on `127.0.0.1:9091` and Alertmanager on
  `127.0.0.1:9093`. Keep them on loopback — metrics describe internals and
  `/metrics` is unauthenticated when `METRICS_TOKEN` is unset.

## A note on stale series

After the target was corrected, `up{job="fastapi"}` briefly returned **two**
series: the new `api:8000` at 1 and the old `localhost:8000` at 0. `APIDown`
fired on the stale one for a few minutes until the samples aged out of the
lookback window. That is expected after changing a target, and it resolves
itself — but if you change a target and see an immediate alert, check the
`instance` label before assuming a real outage.

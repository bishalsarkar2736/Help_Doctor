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

```bash
# 1. Targets must be "up"
curl -s localhost:9091/api/v1/targets | jq '.data.activeTargets[] | {job:.labels.job, health}'

# 2. Rules must be loaded (groups must not be [])
curl -s localhost:9091/api/v1/rules | jq '.data.groups[].name'

# 3. Alertmanager must be discovered (must not be [])
curl -s localhost:9091/api/v1/alertmanagers | jq '.data.activeAlertmanagers'

# 4. Real data must be queryable
curl -s --get localhost:9091/api/v1/query --data-urlencode 'query=login_attempts_total'

# 5. Alerts must reach Alertmanager, not just fire in Prometheus
curl -s localhost:9093/api/v2/alerts | jq '.[].labels.alertname'
```

## The alert rules

Deliberately few. Every rule should be something a human would act on; alerts
that fire on noise train people to ignore the ones that matter.

| alert | severity | why |
|---|---|---|
| `APIDown` | critical | `up == 0`, synthesised by Prometheus, so it fires even when the app is too broken to report anything |
| `APIMetricsUnscrapeable` | warning | target unreachable for 10min — usually `METRICS_TOKEN` misconfigured |
| `HighAPILatency` | warning | p95 > 1s for 10min |
| `LoginFailureSpike` | warning | brute force / credential stuffing |
| `LoginFailureMajority` | warning | >80% of logins failing — attack, or auth is broken |
| `PaymentFailures` | critical | money lost and the patient loses their booking |
| `DatabaseRetries` | warning | deadlocks or connection saturation; usually precedes an outage |
| `DoubleBookingContention` | warning | the guard is working, but firing this often means the UI offers taken slots |

## Metrics are PER PROCESS — this constrains what can be alerted on

Only the `api` container is scraped. `prometheus_client` counters live in the
process that increments them, so **Celery-owned metrics are not collected at
all**: `outbox_*`, `notification_*` and the worker heartbeat all read `0` on
the API's `/metrics` and always will.

Alerting on them would fire permanently. To cover the workers you need either a
metrics endpoint in the worker process or a pushgateway. Until then, Celery
failures are invisible to alerting — **this is a real remaining gap.**

Similarly, with more than one uvicorn worker each process keeps its own
counters and a scrape hits whichever one answers, so counters appear to jump
around. Use `multiprocess` mode or a single worker per container.

## Known instrumentation gaps

* **No HTTP status-code metric.** An error-rate alert ("5xx above 1%") is not
  expressible today. This is the most valuable metric missing — add a counter
  labelled by status class in `RequestLoggingMiddleware`.
* **`api_request_latency_seconds` carries no route label**, so `HighAPILatency`
  cannot say which endpoint is slow.
* **Celery is not scraped** (see above).
* **No Postgres or Redis exporter**, so connection saturation and replication
  lag are invisible.

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
* Replace the Alertmanager receivers in `alertmanager.yml`. They currently
  point at MailHog so the delivery path is real and testable in development;
  they reach nobody in production. Put SMTP/Slack credentials in a mounted
  secret file, not inline — deploy with
  `ALERTMANAGER_CONFIG=./alertmanager.production.yml`.
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

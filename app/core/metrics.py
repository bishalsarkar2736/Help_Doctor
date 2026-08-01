from prometheus_client import Counter, Histogram, Gauge


# ---------------- API Metrics ----------------

api_request_latency = Histogram(
    "api_request_latency_seconds",
    "Time spent processing API requests",
)

# Request counts by outcome. Without this there is no error rate at all — the
# latency histogram above says how long requests took but not whether any of
# them failed, so a deploy that 500s every write would look perfectly healthy
# on the dashboard.
#
# LABEL CARDINALITY IS THE WHOLE DESIGN CONSTRAINT HERE.
#
# `path` is the ROUTE TEMPLATE ("/patients/{patient_id}"), never the requested
# URL. Using the raw path would mint a new time series per patient id, per
# prescription id, per scanner probe — unbounded growth that eventually takes
# Prometheus down with the very system it is meant to watch. Unmatched requests
# collapse to a single "<unmatched>" bucket for the same reason.
http_requests_total = Counter(
    "http_requests_total",
    "HTTP requests by method, route template and status code",
    ["method", "path", "status"],
)


appointment_created_total = Counter(
    "appointment_created_total",
    "Total appointments created",
)

appointment_cancelled_total = Counter(
    "appointment_cancelled_total",
    "Total appointments cancelled",
    ["actor"],
)

appointment_rescheduled_total = Counter(
    "appointment_rescheduled_total",
    "Total appointments rescheduled",
    ["actor"],
)

appointment_confirmed_total = Counter(
    "appointment_confirmed_total",
    "Total appointments confirmed",
    ["actor"],
)

prescriptions_issued_total = Counter(
    "prescriptions_issued_total",
    "Total prescriptions issued (draft -> issued)",
)

# =========================
# PAYMENT METRICS
# =========================

payments_success_total = Counter(
    "payments_success_total",
    "Total payments completed successfully",
)

payments_failed_total = Counter(
    "payments_failed_total",
    "Total payments that failed",
)

# =========================
# AUTH METRICS
# =========================

login_attempts_total = Counter(
    "login_attempts_total",
    "Total login attempts",
    ["result"],  # "success" | "failure"
)

# =========================
# LIVE QUEUE METRICS
# =========================

doctor_queue_length = Gauge(
    "doctor_queue_length",
    "Number of patients waiting in a doctor's live queue",
    ["doctor_id"],
)

# =========================
# BOOKING FAILURE METRICS
# =========================

doctor_double_booking_prevented_total = Counter(
    "doctor_double_booking_prevented_total",
    "Total prevented double booking attempts",
)

doctor_slot_validation_failures_total = Counter(
    "doctor_slot_validation_failures_total",
    "Total invalid appointment slot attempts",
    ["reason"],
)


# =========================
# DATABASE RETRY METRICS
# =========================

db_retry_total = Counter(
    "db_retry_total",
    "Total DB retries",
    ["operation"],
)


# ---------------- Outbox Metrics ----------------

outbox_events_processed_total = Counter(
    "outbox_events_processed_total",
    "Total outbox events processed",
)

outbox_event_failures_total = Counter(
    "outbox_event_failures_total",
    "Total outbox event failures",
)


# ---------------- Worker Metrics ----------------

outbox_processing_time_seconds = Histogram(
    "outbox_processing_time_seconds",
    "Time spent processing outbox events",
)

# ---------------- QUEUE HEALTH ----------------

outbox_queue_size = Gauge(
    "outbox_queue_size",
    "Number of pending outbox events",
)


# ---------------- EVENT LAG ----------------

outbox_event_lag_seconds = Histogram(
    "outbox_event_lag_seconds",
    "Delay between event creation and processing",
)


# ---------------- DLQ METRIC ----------------

outbox_dead_letter_total = Counter(
    "outbox_dead_letter_total",
    "Total events moved to dead letter queue",
)

# how many events are stuck right now
outbox_stuck_events = Gauge(
    "outbox_stuck_events",
    "Number of stuck outbox events (processing timeout exceeded)",
)

# how many events were reclaimed
outbox_reclaimed_total = Counter(
    "outbox_reclaimed_total",
    "Total reclaimed stuck events",
)

outbox_worker_heartbeat = Gauge(
    "outbox_worker_heartbeat",
    "Last heartbeat timestamp of outbox worker",
)


notification_sent_total = Counter(
    "notification_sent_total",
    "Total notifications successfully delivered",
)

notification_failed_total = Counter(
    "notification_failed_total",
    "Total notification delivery failures",
)


medicine_search_total = Counter(
    "medicine_search_total",
    "Total medicine searches",
)

medicine_assistant_queries_total = Counter(
    "medicine_assistant_queries_total",
    "Total medicine assistant queries",
)

medicine_assistant_not_found_total = Counter(
    "medicine_assistant_not_found_total",
    "Total medicine assistant queries with no medicine match",
)

medicine_assistant_success_total = Counter(
    "medicine_assistant_success_total",
    "Total successful medicine assistant responses",
)

medicine_ai_requests_total = Counter(
    "medicine_ai_requests_total",
    "Total medicine AI requests",
)

medicine_ai_failures_total = Counter(
    "medicine_ai_failures_total",
    "Total medicine AI failures",
)

medicine_ai_latency_seconds = Histogram(
    "medicine_ai_latency_seconds",
    "Medicine AI response latency",
)

medicine_ai_tokens_total = Counter(
    "medicine_ai_tokens_total",
    "Total medicine AI tokens consumed",
)
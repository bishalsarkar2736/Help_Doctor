# Security Overview

This documents the security posture of the Help_Doctor backend: what protections
exist, how they're configured, and what remains the operator's responsibility.

---

## Authentication

- **Password hashing:** Argon2 (via passlib) — see
  [`app/security/jwt.py`](../app/security/jwt.py). No plaintext or weak hashes.
- **Access tokens:** short-lived JWTs (`ACCESS_TOKEN_EXPIRE_MINUTES`, default 60),
  signed with `JWT_SECRET_KEY` (enforced ≥ 32 chars) using `HS256`.
- **Refresh tokens:** opaque, **DB-backed**, rotated on use, and revocable
  ([`app/models/refresh_token.py`](../app/models/refresh_token.py),
  [`app/services/auth_service.py`](../app/services/auth_service.py)). Logout,
  password change, and password reset all revoke tokens.
- **Google OAuth:** verifies issuer and `email_verified`
  ([`app/security/google_oauth.py`](../app/security/google_oauth.py)).

## Authorization (RBAC)

- Roles: `ADMIN`, `DOCTOR`, `RECEPTIONIST`, `PATIENT`.
- Enforced with `require_roles(...)` dependencies
  ([`app/security/rbac.py`](../app/security/rbac.py)) applied on admin and
  clinical routes.
- **Multi-tenant isolation:** clinic-scoped access is enforced in services (e.g.
  a doctor cannot refund or view another clinic's records). Covered by
  `tests/services/test_tenant_isolation.py`.

## Transport & headers

- **Security headers** on every response
  ([`app/try_except/security_headers_middleware.py`](../app/try_except/security_headers_middleware.py)):
  `Strict-Transport-Security`, `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy`.
- **TLS is not terminated by the app** — you must front it with HTTPS
  (see [DEPLOYMENT.md §4.4](DEPLOYMENT.md#44-tls--reverse-proxy--not-yet-included)).
  The HSTS header only takes effect once the app is actually served over HTTPS.

## CORS

- Driven by `ALLOWED_ORIGINS` (comma-separated) — see [CONFIGURATION.md](CONFIGURATION.md).
- `allow_credentials=True`, so origins **must** be an explicit list — never `*`.
  Set it to your real frontend origin(s) in production.

## Rate limiting

Implemented with SlowAPI ([`app/core/limiter.py`](../app/core/limiter.py)):

| Endpoint(s)                         | Limit     |
|-------------------------------------|-----------|
| Login / forgot / reset password     | 5 / min   |
| bKash payment webhook               | 30 / min  |
| bKash initiate                      | 10 / min  |
| Medicine AI assistant               | 10 / min  |

Consider extending limits to other write-heavy or enumeration-prone endpoints
as traffic patterns emerge.

## Payments

- **No card data is stored.** Only gateway references (`transaction_id`,
  `gateway_payment_id`) are persisted — card handling is fully delegated to
  bKash/Nagad/Rocket. This keeps the app out of PCI-DSS cardholder-data scope.
- **Webhook integrity:** the bKash webhook re-verifies status and amount
  server-side against the gateway before acting, is idempotent (idempotency
  keys), and is rate-limited.
- **Refund correctness:** a payment is marked `REFUNDED` only **after** the
  gateway confirms the refund `Completed`; otherwise it raises and rolls back.
  Every payment event is written to `payment_audit_log`.

## Secrets management

- No secrets in source control (the previously hardcoded Alembic DB URL and
  in-code defaults were removed).
- `.env` is git-ignored and is for **local dev only**.
- In production, inject secrets from a secret manager. Rotate any credential
  that ever existed in dev/git before go-live.

## Input validation & injection

- All queries go through SQLAlchemy ORM / parameterized statements — no raw SQL
  string interpolation.
- **File uploads** (clinic logos, doctor signatures) validate content-type
  against an allowlist and enforce a size cap
  ([`app/services/clinic_logo_service.py`](../app/services/clinic_logo_service.py),
  [`app/services/doctor_service.py`](../app/services/doctor_service.py)).

## Error handling & information disclosure

- A global exception handler returns **sanitized** JSON — no stack traces or DB
  errors leak to clients ([`app/errors/handlers.py`](../app/errors/handlers.py)).
- All errors are logged server-side with request/correlation IDs for triage.

## Auditing

- Payment events → `payment_audit_log`.
- Admin actions → `activity_log` / `admin_activity_log`.
- Appointment changes → `appointment_audit_log` / `appointment_history`.

---

## Operator responsibilities (not enforced by code)

- [ ] Terminate TLS in front of the app; force HTTPS.
- [ ] Set `ENV=production` and `DEBUG=false` (a startup guard rejects `DEBUG=true`
      in production).
- [ ] Set a strong random `JWT_SECRET_KEY` and `METRICS_TOKEN`.
- [ ] Restrict `ALLOWED_ORIGINS` to your real frontend.
- [ ] Rotate all dev secrets (DB password, JWT, VAPID, mail).
- [ ] Keep dependencies patched; re-run `pip install -r requirements.txt` against
      updated pins periodically.

## Compliance considerations (decide deliberately)

- **PHI at rest:** patient demographics and prescription content are stored in
  plaintext columns, relying on database/disk-level encryption. If your
  regulatory context (e.g. HIPAA-equivalent) requires application-level field
  encryption, that must be added.
- **Data retention:** patient/prescription records currently hard-delete via
  `ON DELETE CASCADE` from the user. Medical-record retention usually calls for
  soft-delete instead — a product/legal decision.

---

## Reporting a vulnerability

Establish a private channel (security contact email or a private issue process)
before launch, and document it here for whoever operates the system.

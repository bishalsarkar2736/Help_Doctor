"""Refuse a production environment file that would deploy something unsafe.

`Settings` already rejects the two things that make the app refuse to start —
DEBUG in production, and the fake payment gateway. This checks the larger set
that loads perfectly and is still wrong: localhost origins, an unset metrics
token that silently kills monitoring, secrets left at their example values, a
missing MFA encryption key, backups with nowhere offsite to go.

Every check here is a mistake that has actually been made in this project or
that its own configuration invites.

    python scripts/check_production_env.py .env.production

Exit code is 0 only if nothing is wrong, so it works as a deploy gate.
"""

import os
import re
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

import yaml

REPO = Path(__file__).resolve().parent.parent

# The subdomain rule is REUSED, not restated. app/domain/clinics/subdomain.py is
# what the tenant resolver and the Host allowlist both consult, and a second
# copy here would be a third opinion that drifts from them silently — the whole
# point of this check is that the pieces agree.
#
# Safe to import from a deploy gate: that module depends on `re` and nothing
# else, so this pulls in no application dependencies and needs no installed
# environment. sys.path is extended because the script's own directory, not the
# repo root, is sys.path[0] when it runs as `python scripts/...`.
sys.path.insert(0, str(REPO))

from app.domain.clinics.subdomain import (  # noqa: E402
    InvalidSubdomain,
    validate_subdomain,
)

# Both monitoring containers run as nobody. Measured:
#   docker run --rm --entrypoint id prom/prometheus   -> uid=65534(nobody)
#   docker run --rm --entrypoint id prom/alertmanager -> uid=65534(nobody)
# A mounted secret they cannot read fails at USE time, not at startup, so the
# container looks healthy while the thing it exists to do never happens.
SECRET_READER_UID = 65534

# Where compose mounts ./secrets inside each container. A *_file directive
# pointing anywhere else names a path that does not exist at runtime.
ALERTMANAGER_SECRETS_MOUNT = PurePosixPath("/etc/alertmanager/secrets")

ALERTMANAGER_PRODUCTION_CONFIG = REPO / "alertmanager.production.yml"


def _describe(path: Path) -> str:
    """Repo-relative where possible, so messages are copy-pasteable."""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def check_mounted_secret(path: Path, *, consequence: str) -> bool:
    """Is this file present, regular, and readable by the container that needs it?

    Shared by the Prometheus token and every Alertmanager credential, because
    the failure is identical in all of them and was found the same way twice:
    0600 owned by the deploying user is the mode every instinct reaches for, and
    it is exactly the one that locks out a container running as nobody.
    """
    if not path.exists():
        fail(f"{_describe(path)} does not exist — {consequence}")
        return False

    if not path.is_file():
        fail(f"{_describe(path)} is not a regular file — {consequence}")
        return False

    info = path.stat()

    readable = (
        info.st_mode & 0o004
        or (info.st_uid == SECRET_READER_UID and info.st_mode & 0o400)
        or (info.st_gid == SECRET_READER_UID and info.st_mode & 0o040)
    )

    if not readable:
        fail(
            f"{_describe(path)} is mode {oct(info.st_mode & 0o777)} owned by "
            f"{info.st_uid}:{info.st_gid} — the container runs as "
            f"{SECRET_READER_UID} and cannot read it, so {consequence}. Either "
            f"`chmod 644 {_describe(path)}`, or `chown {SECRET_READER_UID} "
            f"{_describe(path)}` and keep 600."
        )
        return False

    return True

ERRORS: list[str] = []
WARNINGS: list[str] = []
OK: list[str] = []


def fail(msg: str) -> None:
    ERRORS.append(msg)


def warn(msg: str) -> None:
    WARNINGS.append(msg)


def ok(msg: str) -> None:
    OK.append(msg)


def load(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip().strip('"').strip("'")
    return values


# Values shipped in .env.example. Deploying with any of them means the operator
# copied the template and missed a line.
EXAMPLE_VALUES = {
    "JWT_SECRET_KEY": "replace_with_at_least_32_characters",
    "POSTGRES_PASSWORD": "strongpassword",
    "S3_SECRET_KEY": "change_me_in_production",
    "GOOGLE_CLIENT_SECRET": "your_google_client_secret",
    "WHATSAPP_ACCESS_TOKEN": "your_whatsapp_access_token",
}


def check_database_target(env: dict[str, str]) -> None:
    """DATABASE_URL and the POSTGRES_* parts must describe the same database.

    Alembic prefers DATABASE_URL; the application composes its own from the
    parts. If the two disagree, the schema is migrated in one database while
    every query runs against another, and nothing reports it — the app is
    simply missing tables it believes it created.

    The app refuses to start on this now, but a deploy finds out sooner here.
    """
    def _mismatches(url: str, name: str, *, credentials: bool) -> list[str]:
        parsed = urlsplit(url)

        checks = [
            ("host", parsed.hostname, "POSTGRES_HOST"),
            ("database", parsed.path.lstrip("/"), "POSTGRES_DB"),
        ]

        if credentials:
            checks += [
                ("user", unquote(parsed.username or ""), "POSTGRES_USER"),
                ("password", unquote(parsed.password or ""), "POSTGRES_PASSWORD"),
            ]

        found = []

        for label, from_url, key in checks:
            from_parts = env.get(key, "")

            if from_url and from_parts and from_url != from_parts:
                # Values omitted for the password: this runs in deploy logs.
                found.append(
                    f"{label}: {name} and {key} differ"
                    if label == "password"
                    else f"{label}: {name} has {from_url!r}, {key}={from_parts!r}"
                )

        parts_port = env.get("POSTGRES_PORT", "")

        if parsed.port and parts_port and str(parsed.port) != parts_port:
            found.append(
                f"port: {name} has {parsed.port}, POSTGRES_PORT={parts_port!r}"
            )

        return found

    url = env.get("DATABASE_URL", "").strip()
    migration_url = env.get("MIGRATION_DATABASE_URL", "").strip()

    if not url:
        ok("DATABASE_URL unset — the POSTGRES_* parts are the single source")
    else:
        # Credentials are NOT compared: under privilege separation this names
        # the restricted runtime role while the parts describe the owner. Host,
        # port and database still are, because two databases is the failure
        # this check exists for and separation did not change that.
        problems = _mismatches(url, "DATABASE_URL", credentials=False)

        if problems:
            for detail in problems:
                fail(f"DATABASE_URL contradicts the POSTGRES_* settings — {detail}")
        else:
            ok("DATABASE_URL agrees with the POSTGRES_* settings")

    if migration_url:
        # Held to the stricter rule: this and the POSTGRES_* parts describe the
        # same privileged role, so a half-done rotation is still a mistake.
        problems = _mismatches(
            migration_url, "MIGRATION_DATABASE_URL", credentials=True
        )

        for detail in problems:
            fail(
                "MIGRATION_DATABASE_URL contradicts the POSTGRES_* settings "
                f"— {detail}"
            )

        if not problems:
            ok("MIGRATION_DATABASE_URL agrees with the POSTGRES_* settings")

    # Informational, never fatal: an environment that has not adopted privilege
    # separation is not broken, it is just running as it did before.
    runtime_role = unquote(urlsplit(url).username or "") if url else ""

    if runtime_role and runtime_role != env.get("POSTGRES_USER", ""):
        ok(f"runtime connects as {runtime_role!r}, not the owning role")
    else:
        warn(
            "runtime and migrations share one credential — the application "
            "runs with the owner's privileges (see scripts/create_app_role.sh)"
        )


def check_allowed_hosts(env: dict[str, str]) -> None:
    """The Host allowlist must name real hostnames.

    nginx serves on a catch-all server_name and forwards the client's Host
    verbatim, so this list is what stands between a forged header and anything
    downstream that trusts it. The app refuses to start on these, but a deploy
    should not get that far.
    """
    raw = env.get("ALLOWED_HOSTS", "").strip()

    if not raw:
        fail("ALLOWED_HOSTS is not set — the app will refuse to start")
        return

    hosts = {host.strip().lower() for host in raw.split(",") if host.strip()}

    # Only ever reachable in-process; its presence means the development
    # default was shipped rather than edited.
    if "testserver" in hosts:
        fail("ALLOWED_HOSTS still contains the test-only hostname 'testserver'")
        return

    loopback = {"localhost", "127.0.0.1", "[::1]", "::1"}

    if not hosts - loopback:
        fail(
            "ALLOWED_HOSTS names only loopback — every request nginx forwards "
            "would be rejected"
        )
        return

    ok(f"ALLOWED_HOSTS names {len(hosts - loopback)} routable hostname(s)")


def _wildcard_base(env: dict[str, str]) -> str | None:
    """The base of a `*.base` entry in ALLOWED_HOSTS, if there is one."""
    raw = env.get("ALLOWED_HOSTS", "")

    for host in raw.split(","):
        host = host.strip().lower()

        if host.startswith("*."):
            return host[2:]

    return None


def check_clinic_base_domain(env: dict[str, str]) -> None:
    """The apex tenant subdomains hang off, and its agreement with ALLOWED_HOSTS.

    Two settings, read by different code, with nothing at runtime to notice they
    disagree: TrustedHostMiddleware decides what may arrive from ALLOWED_HOSTS,
    the tenant resolver decides what it means from CLINIC_BASE_DOMAIN. Configure
    one without the other and the failure is silent and confusing — a wildcard
    with no base domain 404s every tenant host, a base domain with no wildcard
    400s every tenant host, and neither says why.

    Empty is allowed and means single-tenant: one hostname, no host-based tenant
    resolution. Only the MISMATCH is refused.
    """
    value = env.get("CLINIC_BASE_DOMAIN", "").strip()
    wildcard = _wildcard_base(env)

    if not value:
        if wildcard:
            fail(
                f"ALLOWED_HOSTS contains '*.{wildcard}' but CLINIC_BASE_DOMAIN "
                "is empty — those hosts would pass the allowlist and then "
                "resolve to no clinic, so every tenant request 404s"
            )
            return

        ok("CLINIC_BASE_DOMAIN empty — single-tenant, host routing disabled")
        return

    if value.startswith("*.") or "*" in value:
        fail(
            f"CLINIC_BASE_DOMAIN is {value!r} — it names the base domain "
            "itself, not a pattern. Write 'example.com', not '*.example.com'"
        )
        return

    if "://" in value or "/" in value or ":" in value:
        fail(
            f"CLINIC_BASE_DOMAIN is {value!r} — a bare hostname is expected, "
            "with no scheme, port or path"
        )
        return

    labels = value.strip(".").split(".")

    if len(labels) < 2 or not all(labels):
        fail(
            f"CLINIC_BASE_DOMAIN is {value!r} — a base domain needs at least "
            "two labels, or a tenant subdomain would sit directly under a TLD"
        )
        return

    # Each label held to the same rule a tenant label is, so a base domain
    # cannot be something no certificate would ever cover.
    for label in labels:
        try:
            validate_subdomain(label)

        except InvalidSubdomain as exc:
            fail(f"CLINIC_BASE_DOMAIN label {label!r} is not a valid DNS label: {exc}")
            return

    if wildcard is None:
        ok(f"CLINIC_BASE_DOMAIN={value} (no wildcard in ALLOWED_HOSTS)")
        return

    if wildcard != value:
        fail(
            f"ALLOWED_HOSTS allows '*.{wildcard}' but CLINIC_BASE_DOMAIN is "
            f"'{value}' — the allowlist and the tenant resolver would disagree "
            "about which hosts are tenants, and nothing at runtime reports it"
        )
        return

    ok(f"CLINIC_BASE_DOMAIN={value} matches the ALLOWED_HOSTS wildcard")


def check_trusted_proxy_ips(env: dict[str, str]) -> None:
    """The addresses whose X-Forwarded-For this deployment believes.

    Empty behind a reverse proxy is not a safe default in production, it is a
    broken one: every anonymous caller is attributed to the proxy, so a per-IP
    rate limit becomes a per-DEPLOYMENT rate limit that throttles everyone
    together while stopping no individual.

    Too wide is worse. Trusting every source makes the header client-controlled,
    and a caller can then mint a fresh rate-limit identity per request.
    """
    import ipaddress

    raw = env.get("TRUSTED_PROXY_IPS", "").strip()

    if not raw:
        fail(
            "TRUSTED_PROXY_IPS is empty — behind a reverse proxy every request "
            "is attributed to the proxy's address, so per-IP rate limits apply "
            "to the whole deployment at once. Name the proxy's network."
        )
        return

    entries = [entry.strip() for entry in raw.split(",") if entry.strip()]

    if not entries:
        fail("TRUSTED_PROXY_IPS contains only separators")
        return

    for entry in entries:
        if entry == "*":
            fail(
                "TRUSTED_PROXY_IPS is '*' — that trusts X-Forwarded-For from "
                "any source, which makes it client-controlled and per-IP rate "
                "limits trivially evadable. Name the proxy's network."
            )
            return

        try:
            network = ipaddress.ip_network(entry, strict=False)

        except ValueError as exc:
            fail(
                f"TRUSTED_PROXY_IPS entry {entry!r} is not an IP address or "
                f"CIDR block: {exc}"
            )
            return

        # 0.0.0.0/0 and ::/0 are "*" spelled as a network.
        if network.prefixlen == 0:
            fail(
                f"TRUSTED_PROXY_IPS entry {entry!r} covers every address — the "
                "same hazard as '*'. Name the proxy's network."
            )
            return

    ok(f"TRUSTED_PROXY_IPS names {len(entries)} trusted source(s)")


def check_metrics_scrape_credential(env: dict[str, str]) -> None:
    """The other half of METRICS_TOKEN: whether Prometheus can actually send it.

    Setting METRICS_TOKEN protects /metrics and simultaneously locks Prometheus
    out, because the scraper has to be given the same value. That half is
    invisible from the env file -- the API is healthy, the token is set, the
    checklist is ticked, and the fastapi target sits DOWN with 401 while every
    alert built on API metrics quietly has no data.

    So this reads the scraper's side too: the token file must exist, hold
    EXACTLY the same value, and the production Prometheus config must be the one
    that reads it.
    """
    token = env.get("METRICS_TOKEN", "")

    if not token:
        # Already reported as an error by check(); nothing further to compare.
        return

    secret = REPO / "secrets" / "metrics_token"

    if not secret.is_file():
        # Deliberately not an early return: a deployer in this state needs the
        # PROMETHEUS_CONFIG guidance below more than anyone, not less.
        fail(
            f"METRICS_TOKEN is set but {secret.relative_to(REPO)} does not exist "
            "— Prometheus has no credential to send and every scrape 401s. "
            "Create it: printf '%s' \"$METRICS_TOKEN\" > secrets/metrics_token"
        )
    else:
        content = secret.read_text()

        if not content.strip():
            fail(f"{secret.relative_to(REPO)} is empty — scrapes will 401")
        elif content != token:
            hint = (
                " (it has a trailing newline — use printf, not echo)"
                if content.rstrip("\n") == token
                else ""
            )
            fail(
                f"{secret.relative_to(REPO)} does not match METRICS_TOKEN{hint} "
                "— Prometheus will authenticate with the wrong value and every "
                "scrape 401s"
            )
        else:
            ok("secrets/metrics_token matches METRICS_TOKEN")

        # Counter-intuitive, and measured: Prometheus runs as nobody (65534),
        # so a 0600 file owned by the deploying user is UNREADABLE to it and
        # every scrape fails with "unable to read authorization credentials".
        # 0640 fails too. The file has to be readable by that uid.
        check_mounted_secret(secret, consequence="every scrape fails with 401")

    production_config = REPO / "prometheus.production.yml"

    if not production_config.is_file():
        fail(f"{production_config.name} is missing — production has no authenticated scrape config")
        return

    if "bearer_token_file" not in production_config.read_text():
        fail(
            f"{production_config.name} does not set bearer_token_file — "
            "Prometheus would scrape production /metrics unauthenticated and "
            "receive 401"
        )
    else:
        ok("prometheus.production.yml sends the bearer token")

    warn(
        "deploy with PROMETHEUS_CONFIG=./prometheus.production.yml, or compose "
        "mounts the unauthenticated dev config and the fastapi target stays DOWN"
    )


def alertmanager_secret_references(config: object) -> list[str]:
    """Every `*_file` value in the config, however deeply nested.

    Derived from the config rather than hard-coded, so adding a receiver that
    reads a new credential does not silently escape the check. Alertmanager
    spells them `smtp_auth_password_file`, `api_url_file`, `auth_password_file`,
    `bearer_token_file` and so on -- the suffix is the stable part.
    """
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(key, str) and key.endswith("_file") and isinstance(value, str):
                    found.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(config)

    return found


def check_alertmanager_secrets(env: dict[str, str]) -> None:
    """Can Alertmanager actually read the credentials it is configured to use?

    THE FAILURE THIS EXISTS FOR, reproduced before it was written:
    prom/alertmanager runs as nobody (65534) and the mounted secrets are 0600
    owned by the deploying user. Alertmanager STARTS cleanly, `amtool
    check-config` returns SUCCESS, the HTTP API answers 200, and Prometheus
    shows alerts firing. Delivery fails only at send time:

        notify retry canceled due to unrecoverable error after 1 attempts:
        open /etc/alertmanager/secrets/slack_webhook: permission denied

        find auth mechanism: could not read
        /etc/alertmanager/secrets/smtp_password: permission denied

    Measured: 54 attempts, 54 failures, nothing delivered. No page, no email, no
    Slack message -- for every rule in alerts.yml. Unlike the Prometheus token,
    no static validator catches this and no scraped metric reveals it, so the
    deploy gate is the only place it can be caught before an incident.
    """
    if not ALERTMANAGER_PRODUCTION_CONFIG.is_file():
        fail(
            f"{ALERTMANAGER_PRODUCTION_CONFIG.name} is missing — production has "
            "no alert delivery configuration"
        )
        return

    try:
        config = yaml.safe_load(ALERTMANAGER_PRODUCTION_CONFIG.read_text())
    except yaml.YAMLError as error:
        fail(f"{ALERTMANAGER_PRODUCTION_CONFIG.name} is not valid YAML: {error}")
        return

    references = alertmanager_secret_references(config)

    if not references:
        warn(
            f"{ALERTMANAGER_PRODUCTION_CONFIG.name} references no *_file secrets "
            "— credentials are either inline (a committed secret) or absent"
        )
        return

    for reference in sorted(set(references)):
        # normpath collapses `..` so a reference cannot climb out of the mount
        # and read, say, /etc/passwd or a file the operator never reviewed.
        resolved = PurePosixPath(os.path.normpath(reference))

        if not resolved.is_relative_to(ALERTMANAGER_SECRETS_MOUNT):
            fail(
                f"{ALERTMANAGER_PRODUCTION_CONFIG.name} reads {reference!r}, "
                f"which is outside {ALERTMANAGER_SECRETS_MOUNT} — compose mounts "
                "only that directory, so the file does not exist at runtime"
            )
            continue

        host_path = REPO / "secrets" / resolved.relative_to(ALERTMANAGER_SECRETS_MOUNT)

        if check_mounted_secret(
            host_path,
            consequence=(
                f"Alertmanager cannot deliver notifications through {reference} "
                "— alerts fire and reach nobody"
            ),
        ):
            ok(f"{_describe(host_path)} is readable by Alertmanager")


def check(env: dict[str, str]) -> None:
    # --- the app refuses to start on these, but say so clearly here ---------
    if env.get("ENV") != "production":
        fail(f"ENV must be 'production', got {env.get('ENV')!r}")
    else:
        ok("ENV=production")

    if env.get("DEBUG", "").lower() in ("true", "1", "yes"):
        fail("DEBUG is enabled — Settings will refuse to start")
    else:
        ok("DEBUG is off")

    if env.get("PAYMENT_GATEWAY") == "fake":
        fail("PAYMENT_GATEWAY=fake is not allowed in production")

    check_database_target(env)
    check_allowed_hosts(env)
    check_clinic_base_domain(env)
    check_trusted_proxy_ips(env)
    check_metrics_scrape_credential(env)
    check_alertmanager_secrets(env)

    # --- loads fine, still wrong -------------------------------------------
    for key, example in EXAMPLE_VALUES.items():
        if env.get(key) == example:
            fail(f"{key} is still the .env.example placeholder")

    # Generic marker, so a template can ship as an obvious blank that this
    # refuses rather than as something that quietly looks configured.
    for key, value in env.items():
        if re.search(r"REPLACE|CHANGEME|TODO|xxxx", value, re.IGNORECASE):
            fail(f"{key} still contains a placeholder marker: {value!r}")

    jwt = env.get("JWT_SECRET_KEY", "")
    if len(jwt) < 32:
        fail(f"JWT_SECRET_KEY is {len(jwt)} chars; needs at least 32")
    else:
        ok("JWT_SECRET_KEY length")

    # Localhost anywhere public-facing means the deployment was never pointed
    # at its real domain. CORS in particular fails closed and confusingly:
    # every browser request is rejected while curl works fine.
    for key in ("ALLOWED_ORIGINS", "FRONTEND_URL", "BASE_URL"):
        value = env.get(key, "")
        if "localhost" in value or "127.0.0.1" in value:
            fail(f"{key} still points at localhost: {value!r}")
        elif value:
            ok(f"{key} is a real host")

    for key in ("ALLOWED_ORIGINS", "FRONTEND_URL", "BASE_URL"):
        value = env.get(key, "")
        if value and value.startswith("http://"):
            fail(f"{key} is http:// — patient data must not travel in cleartext")

    # /metrics returns 404 in production when this is unset, so monitoring
    # stops the moment ENV flips and nothing says why.
    if not env.get("METRICS_TOKEN"):
        fail(
            "METRICS_TOKEN is unset — /metrics 404s under ENV=production and "
            "Prometheus goes blind"
        )
    else:
        ok("METRICS_TOKEN set")

    # Without a dedicated key it is derived from JWT_SECRET_KEY, so rotating
    # the JWT secret would make every stored MFA secret undecryptable.
    if not env.get("MFA_SECRET_ENCRYPTION_KEYS"):
        fail(
            "MFA_SECRET_ENCRYPTION_KEYS is unset — the key is derived from "
            "JWT_SECRET_KEY, so rotating that locks every MFA user out"
        )
    else:
        ok("MFA_SECRET_ENCRYPTION_KEYS set")

    # A copy on the same host is not a backup.
    if not env.get("OFFSITE_BUCKET"):
        fail(
            "OFFSITE_BUCKET is unset — backups live only on this host, so one "
            "disk failure loses the database and every backup of it"
        )
    else:
        ok("offsite backup target configured")

    if env.get("STORAGE_BACKEND") != "s3":
        warn(
            "STORAGE_BACKEND is not 's3' — fine for a single replica, but "
            "uploads will 404 as soon as a second one runs"
        )
    else:
        ok("STORAGE_BACKEND=s3")

    if not env.get("RATE_LIMIT_STORAGE_URI"):
        warn(
            "RATE_LIMIT_STORAGE_URI is unset — limits are per-process, so N "
            "replicas allow N times the configured rate"
        )

    if env.get("MFA_REQUIRED_ROLES", "") == "":
        warn("MFA_REQUIRED_ROLES is empty — no role is required to use MFA")

    # Weak or duplicated secrets.
    seen: dict[str, str] = {}
    for key in ("JWT_SECRET_KEY", "POSTGRES_PASSWORD", "S3_SECRET_KEY"):
        value = env.get(key, "")
        if not value:
            continue
        if value in seen:
            fail(f"{key} reuses the same value as {seen[value]}")
        seen[value] = key

    # Duplicate keys silently take the last value — this file had exactly that
    # with ACCESS_TOKEN_EXPIRE_MINUTES set twice.
    raw = Path(sys.argv[1]).read_text().splitlines()
    keys = [
        line.split("=", 1)[0].strip()
        for line in raw
        if line.strip() and not line.strip().startswith("#") and "=" in line
    ]
    duplicates = {k for k in keys if keys.count(k) > 1}
    if duplicates:
        fail(f"duplicate keys (last one silently wins): {sorted(duplicates)}")
    else:
        ok("no duplicate keys")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python scripts/check_production_env.py <env-file>")
        return 2

    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"no such file: {path}")
        return 2

    check(load(path))

    print(f"\nchecking {path}\n")
    for msg in OK:
        print(f"  [ok  ] {msg}")
    for msg in WARNINGS:
        print(f"  [warn] {msg}")
    for msg in ERRORS:
        print(f"  [FAIL] {msg}")

    print(f"\n{len(OK)} ok, {len(WARNINGS)} warnings, {len(ERRORS)} errors")

    if ERRORS:
        print("\nNot safe to deploy.")
        return 1

    print("\nProduction environment looks sane.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

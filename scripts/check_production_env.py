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

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

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
    url = env.get("DATABASE_URL", "").strip()

    if not url:
        ok("DATABASE_URL unset — the POSTGRES_* parts are the single source")
        return

    parsed = urlsplit(url)

    mismatches = []

    for label, from_url, key in (
        ("host", parsed.hostname, "POSTGRES_HOST"),
        ("database", parsed.path.lstrip("/"), "POSTGRES_DB"),
        ("user", unquote(parsed.username or ""), "POSTGRES_USER"),
        ("password", unquote(parsed.password or ""), "POSTGRES_PASSWORD"),
    ):
        from_parts = env.get(key, "")

        if from_url and from_parts and from_url != from_parts:
            # Values omitted for the password: this runs in deploy logs.
            detail = (
                f"{label}: DATABASE_URL and {key} differ"
                if label == "password"
                else f"{label}: DATABASE_URL has {from_url!r}, {key}={from_parts!r}"
            )
            mismatches.append(detail)

    url_port = parsed.port
    parts_port = env.get("POSTGRES_PORT", "")

    if url_port and parts_port and str(url_port) != parts_port:
        mismatches.append(
            f"port: DATABASE_URL has {url_port}, POSTGRES_PORT={parts_port!r}"
        )

    if mismatches:
        for detail in mismatches:
            fail(f"DATABASE_URL contradicts the POSTGRES_* settings — {detail}")
    else:
        ok("DATABASE_URL agrees with the POSTGRES_* settings")


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

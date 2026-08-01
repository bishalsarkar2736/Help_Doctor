"""Create the first clinic the way a real deployment has to.

Deliberately goes through the HTTP API as the platform super admin rather than
inserting a row. A brand new production deployment has no clinic, and the only
supported way to get one is: bootstrap the super admin, log in, POST a clinic.
Nothing had ever exercised that path end to end — the seeder assumes a clinic
already exists and stops with "No clinic exists. Bootstrap one before seeding".

Running it here means the day-one bootstrap is validated on staging before
anyone performs it against production, where a failure is discovered with no
users and no way in.

Idempotent: if a clinic already exists, it says so and exits 0.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = os.getenv("STAGING_API_URL", "http://127.0.0.1:18000")
EMAIL = os.getenv("SUPER_ADMIN_EMAIL", "staging.owner@example.com")
PASSWORD = os.getenv("SUPER_ADMIN_PASSWORD", "Staging-Owner-9417-Pass")
CLINIC_NAME = os.getenv("STAGING_CLINIC_NAME", "Staging Clinic")


def request(method: str, path: str, token: str | None = None, body=None, form=None):
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
    elif body is not None:
        data = json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
    else:
        data, headers = None, {}

    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(
        f"{API}{path}", data=data, headers=headers, method=method
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        return exc.code, detail


def main() -> int:
    status, existing = request("GET", "/clinics")
    if status == 200 and existing:
        print(f"   clinic already exists: {existing[0].get('name')!r} — nothing to do")
        return 0

    status, token = request(
        "POST", "/auth/login", form={"username": EMAIL, "password": PASSWORD}
    )
    if status != 200 or not isinstance(token, dict):
        print(f"   FAILED to log in as the super admin: HTTP {status} {token}")
        return 1

    access = token["access_token"]

    status, created = request(
        "POST",
        "/admin/clinic",
        token=access,
        body={"name": CLINIC_NAME},
    )

    if status not in (200, 201):
        print(f"   FAILED to create the clinic: HTTP {status} {created}")
        print(
            "   This is the day-one bootstrap path. If it does not work here, a "
            "fresh production deployment cannot be brought into service."
        )
        return 1

    print(f"   created clinic {CLINIC_NAME!r} through the API")
    return 0


if __name__ == "__main__":
    sys.exit(main())

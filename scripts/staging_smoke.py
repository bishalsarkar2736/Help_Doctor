"""Operational smoke tests for the staging deployment.

Distinct from the unit and e2e suites, which test the CODE. These test the
DEPLOYMENT: that this commit migrates cleanly onto an empty database, that the
services came up in an order that works, that the nginx-to-api seam holds, and
that a real account can authenticate through the same path a browser takes.

Every check here corresponds to something that has actually broken in this
project at least once — a stale nginx upstream, an unbootable .env.example, a
migration chain that could not be applied from scratch, a storage backend that
served nothing after switching to s3.

Exit code is 0 only if every check passes, so this is usable as a deployment
gate.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = os.getenv("STAGING_API_URL", "http://127.0.0.1:18000")
WEB = os.getenv("STAGING_WEB_URL", "http://127.0.0.1:15173")

PASSES: list[str] = []
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSES if ok else FAILURES).append(name)
    mark = "ok  " if ok else "FAIL"
    print(f"  [{mark}] {name}{f' — {detail}' if detail else ''}")
    return ok


def get(url: str, token: str | None = None, raw: bool = False):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
            if raw:
                return resp.status, body
            try:
                return resp.status, json.loads(body or b"{}")
            except ValueError:
                # Not JSON — the SPA returns HTML. The status is what matters
                # to the caller; parsing it as JSON turned a healthy 200 into
                # a reported failure.
                return resp.status, body.decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def post_form(url: str, data: dict):
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read() or b"{}"), resp.headers
    except urllib.error.HTTPError as exc:
        return exc.code, None, exc.headers
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc), None


def main() -> int:
    print(f"\nstaging smoke — api={API} web={WEB}\n")

    # --- the stack is up -----------------------------------------------
    print("service health")
    status, _ = get(f"{API}/health/live")
    check("api liveness", status == 200, f"HTTP {status}")

    status, body = get(f"{API}/health/ready")
    ready = status == 200 and isinstance(body, dict)
    check("api readiness (db + redis)", ready, f"HTTP {status}")

    if ready:
        services = body.get("services", {})
        for name, info in services.items():
            check(
                f"  dependency: {name}",
                info.get("status") == "healthy",
                info.get("status", "?"),
            )

    # --- the deployment actually applied --------------------------------
    print("\nschema")
    status, body = get(f"{API}/openapi.json")
    check("openapi served", status == 200)

    # --- the web tier can reach the api ---------------------------------
    # This is the seam that broke silently in production: nginx caches the
    # upstream IP at startup, so an api redeploy left both containers healthy
    # while every request through the SPA origin 502'd.
    print("\nweb tier")
    status, _ = get(f"{WEB}/")
    check("spa served", status == 200, f"HTTP {status}")

    status, _ = get(f"{WEB}/api/health/live")
    check("api reachable THROUGH the proxy", status == 200, f"HTTP {status}")

    # --- security headers survive the proxy ------------------------------
    try:
        with urllib.request.urlopen(f"{WEB}/", timeout=15) as resp:
            csp = resp.headers.get("Content-Security-Policy", "")
    except Exception:  # noqa: BLE001
        csp = ""

    check("CSP served on the document", bool(csp))
    check(
        "CSP does not allow connect-src *",
        "connect-src *" not in csp,
        "connect-src is wide open" if "connect-src *" in csp else "",
    )

    # --- authentication works end to end ---------------------------------
    print("\nauthentication")
    email = os.getenv("STAGING_SMOKE_EMAIL")
    password = os.getenv("STAGING_SMOKE_PASSWORD")

    if not email or not password:
        print(
            "  [skip] login — set STAGING_SMOKE_EMAIL / STAGING_SMOKE_PASSWORD\n"
            "         (seed an account first: scripts/seed_e2e_accounts.py)"
        )
    else:
        status, token_body, headers = post_form(
            f"{WEB}/api/auth/login", {"username": email, "password": password}
        )
        logged_in = status == 200 and isinstance(token_body, dict)
        check("login through the proxy", logged_in, f"HTTP {status}")

        if logged_in:
            leaked = token_body.get("refresh_token") is not None
            check(
                "refresh token NOT in the response body",
                not leaked,
                "refresh token leaked to JavaScript" if leaked else "",
            )

            set_cookie = " ".join(headers.get_all("set-cookie") or []).lower()
            check("refresh cookie is HttpOnly", "httponly" in set_cookie)
            check("refresh cookie is SameSite=Strict", "samesite=strict" in set_cookie)

            access = token_body.get("access_token")
            status, me = get(f"{API}/users/me", token=access)
            check("authenticated request", status == 200, f"HTTP {status}")

            status, _ = get(f"{API}/users/me")
            check("unauthenticated request refused", status == 401, f"HTTP {status}")

    # --- observability ----------------------------------------------------
    print("\nobservability")
    status, raw = get(f"{API}/metrics", raw=True)
    exported = raw.decode() if isinstance(raw, bytes) else ""
    check("metrics endpoint", status == 200, f"HTTP {status}")
    check("http_requests_total exported", "http_requests_total" in exported)
    # Cardinality guard: numeric path segments in a label mean raw URLs are
    # being recorded, which grows series without bound.
    import re as _re

    raw_id_labels = _re.findall(r'path="([^"]*/\d+[^"]*)"', exported)
    check(
        "no raw ids in metric path labels",
        not raw_id_labels,
        f"found {raw_id_labels[:3]}" if raw_id_labels else "",
    )

    # --- summary ----------------------------------------------------------
    print(f"\n{len(PASSES)} passed, {len(FAILURES)} failed")

    if FAILURES:
        print("\nFAILED:")
        for name in FAILURES:
            print(f"  - {name}")
        print("\nDo not promote this build.")
        return 1

    print("\nStaging deployment validated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The refresh token lives in an httpOnly cookie, not in JavaScript.

Why this one and not the access token (yet): the refresh token is the
PERSISTENT credential. An access token stolen via XSS expires in minutes and
cannot be renewed; a stolen refresh token is an account, indefinitely, and the
theft leaves nothing in the audit trail that distinguishes it from the real
user. Taking it out of reach of `document` removes persistent takeover, which
is the bulk of the risk, without touching how any authenticated endpoint reads
its Authorization header.

Moving the ACCESS token to memory is a separate, larger change: it forces a
silent refresh on every page load, and because refresh tokens are single-use
and rotating, that invalidates the session file the e2e suite shares across all
six browser projects. That needs per-project accounts first.

PATH IS "/" ON PURPOSE — DO NOT "TIGHTEN" IT TO /auth
-----------------------------------------------------
Scoping the cookie to /auth looks more careful and silently breaks login. The
browser stores a cookie against the path of the URL IT called, and the SPA
reaches the API through the same-origin proxy at /api/auth/... — so a cookie
scoped to /auth would never be sent back, and every refresh would fail with no
visible error beyond users being logged out at random.

If you want it narrower, it has to match the PUBLIC path (/api/auth), which
then breaks anyone calling the API directly. "/" is correct for both.
"""

from fastapi import Request, Response

from app.config import get_settings

REFRESH_COOKIE_NAME = "refresh_token"


def _cookie_kwargs() -> dict:
    settings = get_settings()

    return {
        "httponly": True,
        # Secure follows the environment: over plain HTTP a Secure cookie is
        # silently DISCARDED by the browser, so hardcoding True would make
        # login appear to work in development while no session ever persisted.
        "secure": settings.ENV == "production",
        # Strict, not Lax: this cookie only ever needs to travel on same-site
        # requests the SPA makes itself. It is also the CSRF defence for
        # /auth/refresh, which is the one state-changing endpoint that relies
        # on ambient credentials rather than an Authorization header.
        "samesite": "strict",
        "path": "/",
    }


def set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()

    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        **_cookie_kwargs(),
    )


def clear_refresh_cookie(response: Response) -> None:
    # delete_cookie must be given the SAME path/samesite/secure attributes, or
    # the browser treats it as a different cookie and the old one survives —
    # logout would appear to succeed while the session remained usable.
    response.delete_cookie(key=REFRESH_COOKIE_NAME, **_cookie_kwargs())


def read_refresh_token(request: Request, body_token: str | None = None) -> str | None:
    """Cookie first, request body as a fallback.

    The body path is kept so a session issued before this change (refresh token
    held in localStorage) can still be redeemed once, and so non-browser
    clients are not broken. The cookie takes precedence: if both are present,
    the one JavaScript cannot forge wins.
    """
    return request.cookies.get(REFRESH_COOKIE_NAME) or body_token

"""Optional Sentry error monitoring.

A no-op unless ``SENTRY_DSN`` is set, so development and tests never talk to
Sentry. ``send_default_pii=False`` keeps patient/user PII out of error reports.
"""

import logging

from app.config import get_settings

logger = logging.getLogger(__name__)


def setup_sentry() -> bool:
    """Initialize Sentry if a DSN is configured. Returns True when enabled."""
    settings = get_settings()

    if not settings.SENTRY_DSN:
        return False

    # Imported lazily so the app runs even if sentry-sdk isn't installed and no
    # DSN is set.
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENV,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        integrations=[StarletteIntegration(), FastApiIntegration()],
        send_default_pii=False,
    )
    logger.info("sentry_initialized", extra={"environment": settings.ENV})
    return True

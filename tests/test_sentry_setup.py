from unittest.mock import patch

from app.core.sentry import setup_sentry


def test_sentry_noop_without_dsn():
    # No DSN configured (test env) → disabled, and sentry_sdk.init never called.
    with patch("sentry_sdk.init") as init:
        assert setup_sentry() is False
        init.assert_not_called()


def test_sentry_initializes_when_dsn_set():
    import app.core.sentry as sentry_mod

    class _FakeSettings:
        SENTRY_DSN = "https://public@example.ingest.sentry.io/1"
        ENV = "production"
        SENTRY_TRACES_SAMPLE_RATE = 0.1

    with patch.object(sentry_mod, "get_settings", return_value=_FakeSettings()):
        with patch("sentry_sdk.init") as init:
            assert setup_sentry() is True
            init.assert_called_once()
            kwargs = init.call_args.kwargs
            assert kwargs["dsn"] == _FakeSettings.SENTRY_DSN
            assert kwargs["environment"] == "production"
            assert kwargs["send_default_pii"] is False

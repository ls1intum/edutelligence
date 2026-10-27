from unittest.mock import patch

import pytest
import sentry_sdk

from iris import sentry


@pytest.fixture(autouse=True)
def _fresh_sentry_client():
    """Every test starts and ends without an active Sentry client."""
    sentry_sdk.get_global_scope().set_client(None)
    yield
    sentry_sdk.get_global_scope().set_client(None)


@pytest.mark.parametrize("dsn", [None, "", "   "])
def test_init_without_dsn_does_not_start_sentry(monkeypatch, dsn):
    if dsn is None:
        monkeypatch.delenv("SENTRY_DSN", raising=False)
    else:
        monkeypatch.setenv("SENTRY_DSN", dsn)

    with patch("iris.sentry.sentry_sdk.init") as sdk_init:
        sentry.init()

    sdk_init.assert_not_called()


def test_capture_without_init_sends_nothing(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    sentry.init()

    assert not sentry_sdk.get_client().is_active()
    assert sentry_sdk.capture_exception(ValueError("boom")) is None
    assert sentry_sdk.capture_message("hello") is None


def test_init_with_dsn_passes_it_to_the_sdk(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://key@sentry.example.org/1")

    with patch("iris.sentry.sentry_sdk.init") as sdk_init:
        sentry.init()

    sdk_init.assert_called_once()
    assert sdk_init.call_args.kwargs["dsn"] == "https://key@sentry.example.org/1"

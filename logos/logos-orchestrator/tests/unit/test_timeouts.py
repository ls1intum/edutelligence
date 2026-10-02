"""logos.timeouts: env parsing runs at import time and must never raise.

A malformed deployment value (non-numeric, whitespace-only, negative or
non-finite) must fall back to the default instead of taking the module —
and therefore ``main.py`` — down during import.
"""

import importlib

import pytest

from logos.timeouts import _env_float


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, 1.0),  # unset
        ("", 1.0),  # empty
        ("   ", 1.0),  # whitespace-only (float() would raise ValueError)
        ("abc", 1.0),  # non-numeric (float() would raise ValueError)
        ("-0.5", 1.0),  # negative backoff would poison asyncio.sleep
        ("inf", 1.0),  # non-finite
        ("-inf", 1.0),
        ("nan", 1.0),
        ("0", 0.0),  # valid zero is preserved
        ("2.5", 2.5),
    ],
)
def test_env_float_falls_back_on_invalid_values(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("LOGOS_TEST_FLOAT", raising=False)
    else:
        monkeypatch.setenv("LOGOS_TEST_FLOAT", raw)
    assert _env_float("LOGOS_TEST_FLOAT", 1.0) == expected


def _retry_env_names() -> tuple[str, ...]:
    return (
        "LOGOS_TIMEOUT_S",
        "LOGOS_REQUEST_MAX_ATTEMPTS",
        "LOGOS_REQUEST_RETRY_DEADLINE_S",
        "LOGOS_REQUEST_RETRY_BACKOFF_BASE_S",
        "LOGOS_REQUEST_RETRY_BACKOFF_CAP_S",
    )


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        # Malformed, negative and non-finite values fall back to the
        # defaults — the import must not raise (a bare float() would).
        (
            {
                "LOGOS_REQUEST_MAX_ATTEMPTS": "oops",
                "LOGOS_REQUEST_RETRY_DEADLINE_S": "abc",
                "LOGOS_REQUEST_RETRY_BACKOFF_BASE_S": "-1",
                "LOGOS_REQUEST_RETRY_BACKOFF_CAP_S": "inf",
            },
            (3, 1800.0, 1.0, 15.0),
        ),
        # Whitespace-only and empty fall back as well (float() would raise).
        (
            {
                "LOGOS_REQUEST_MAX_ATTEMPTS": "   ",
                "LOGOS_REQUEST_RETRY_DEADLINE_S": "",
                "LOGOS_REQUEST_RETRY_BACKOFF_BASE_S": "nan",
                "LOGOS_REQUEST_RETRY_BACKOFF_CAP_S": "-inf",
            },
            (3, 1800.0, 1.0, 15.0),
        ),
        # Valid values are honoured end to end.
        (
            {
                "LOGOS_REQUEST_MAX_ATTEMPTS": "7",
                "LOGOS_REQUEST_RETRY_DEADLINE_S": "42.5",
                "LOGOS_REQUEST_RETRY_BACKOFF_BASE_S": "0.25",
                "LOGOS_REQUEST_RETRY_BACKOFF_CAP_S": "3",
            },
            (7, 42.5, 0.25, 3.0),
        ),
    ],
)
def test_retry_settings_parse_at_import_time(monkeypatch, env, expected):
    """The internal-retry settings are read at import time, so a malformed
    deployment value must fall back to the default instead of raising and
    preventing the orchestrator from starting. A reload re-runs the module
    (a pure settings module) with the test's environment.

    importlib (not ``import logos.timeouts as …``): the package's __init__
    replaces sys.modules['logos'] with logos.main, so the ``as`` form's
    attribute lookup would miss the submodule."""
    timeouts = importlib.import_module("logos.timeouts")

    for name in _retry_env_names():
        monkeypatch.delenv(name, raising=False)
    for name, raw in env.items():
        monkeypatch.setenv(name, raw)
    try:
        importlib.reload(timeouts)
        assert timeouts._REQUEST_MAX_ATTEMPTS == expected[0]
        assert timeouts._REQUEST_RETRY_DEADLINE_S == expected[1]
        assert timeouts._REQUEST_RETRY_BACKOFF_BASE_S == expected[2]
        assert timeouts._REQUEST_RETRY_BACKOFF_CAP_S == expected[3]
    finally:
        for name in _retry_env_names():
            monkeypatch.delenv(name, raising=False)
        importlib.reload(timeouts)

"""logos.timeouts: env parsing runs at import time and must never raise.

A malformed deployment value (non-numeric, whitespace-only, negative or
non-finite) must fall back to the default instead of taking the module —
and therefore ``main.py`` — down during import.
"""

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

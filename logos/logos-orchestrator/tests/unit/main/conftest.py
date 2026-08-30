"""Shared fixtures for the main.py unit tests."""

from __future__ import annotations

import pytest

import logos as main


@pytest.fixture(autouse=True)
def _clear_historic_max_context_cache():
    """Drop the historic-max-context TTL cache around every test.

    ``main._historic_max_context_by_model`` caches its database result for a
    few seconds, and the tests monkeypatch ``main.DBManager`` per test —
    without the clear, one test's seeded database would leak into the next
    within the TTL window.

    The import must be ``import logos as main``, exactly like the test
    modules: ``logos/__init__`` replaces the package in ``sys.modules`` with
    the ``logos.main`` module, so ``from logos import main`` would bind a
    second, unused load of the same file whose cache no test ever touches.
    """
    main._clear_historic_max_context_cache()
    yield
    main._clear_historic_max_context_cache()

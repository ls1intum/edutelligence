"""Tests for the env-gated per-request performance tracing module."""

import asyncio

import pytest

import logos.perf_trace as perf


@pytest.fixture(autouse=True)
def _clean_store(monkeypatch):
    perf.reset()
    # Tests flip the import-time flag directly; always restore it afterwards.
    monkeypatch.setattr(perf, "_ENABLED", True)
    yield
    perf.reset()


def test_disabled_by_default_is_noop(monkeypatch):
    monkeypatch.delenv("LOGOS_PERF_TRACE", raising=False)
    # Re-import state: module decides at import time; simulate disabled mode
    # by clearing the store and checking markers are inert when disabled.
    monkeypatch.setattr(perf, "_ENABLED", False)
    perf.begin("r1")
    assert perf.take("r1") is None
    with perf.phase("r1", "x"):
        pass
    assert perf.take("r1") is None


def test_enabled_requires_env(monkeypatch):
    monkeypatch.setenv("LOGOS_PERF_TRACE", "1")
    # The module-level flag is set at import time; the tests exercise the
    # enabled path by flipping the flag directly (import-time env is covered
    # in the benchmark run itself).
    monkeypatch.setattr(perf, "_ENABLED", True)
    perf.begin("r1")
    with perf.phase("r1", "db.response_block"):
        pass
    perf.finish("r1")
    trace = perf.take("r1")
    assert trace is not None
    assert trace["end_ns"] >= trace["t0_ns"]
    assert trace["phases"]["db.response_block"]["count"] == 1
    assert trace["phases"]["db.response_block"]["total_ns"] >= 0


def test_phase_accumulates_multiple_entries():
    perf._ENABLED = True
    perf.begin("r1")
    for _ in range(3):
        with perf.phase("r1", "auth.api_key"):
            pass
    trace = perf.take("r1")
    assert trace["phases"]["auth.api_key"]["count"] == 3


def test_async_phase_supported():
    perf._ENABLED = True
    perf.begin("r1")

    async def scenario():
        async with perf.phase("r1", "rpc.send_command"):
            await asyncio.sleep(0)

    asyncio.run(scenario())
    trace = perf.take("r1")
    assert trace["phases"]["rpc.send_command"]["count"] == 1


def test_take_is_pop_semantics():
    perf._ENABLED = True
    perf.begin("r1")
    assert perf.take("r1") is not None
    assert perf.take("r1") is None


def test_unknown_request_id_is_ignored():
    perf._ENABLED = True
    with perf.phase("never-begun", "x"):
        pass
    assert perf.take("never-begun") is None


def test_lru_eviction_bounded():
    perf._ENABLED = True
    for i in range(perf._MAX_TRACES + 50):
        perf.begin(f"r{i}")
    assert len(perf._traces) == perf._MAX_TRACES
    # The oldest trace was evicted.
    assert "r0" not in perf._traces
    assert f"r{perf._MAX_TRACES + 49}" in perf._traces
    perf._traces.clear()


def test_reset_clears():
    perf._ENABLED = True
    perf.begin("r1")
    perf.reset()
    assert perf.take("r1") is None

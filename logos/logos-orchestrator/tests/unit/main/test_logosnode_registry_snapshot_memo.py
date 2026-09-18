"""peek_runtime_snapshot memoisation .

The scheduler and the capacity planner call peek_runtime_snapshot several
times per request; the rebuild re-sorts the model sets and copies the event
backlog, so the registry memoises the assembled dict per
ProviderSession.snapshot_version. The version moves on exactly the
mutations that change a peek-visible field — every one of them must
invalidate the memo, and a session detach must drop the entry so a fresh
session on the same provider_id cannot be served the old dict.
"""

from __future__ import annotations

import pytest

from logos.logosnode_registry import LogosNodeRuntimeRegistry, ProviderSession

PROVIDER = 7


def _make_registry() -> LogosNodeRuntimeRegistry:
    registry = LogosNodeRuntimeRegistry()
    registry._sessions[PROVIDER] = ProviderSession(  # noqa: SLF001
        provider_id=PROVIDER, worker_id="worker-a", websocket=object()
    )
    return registry


def _session(registry: LogosNodeRuntimeRegistry) -> ProviderSession:
    return registry._sessions[PROVIDER]  # noqa: SLF001


def test_unknown_provider_returns_none():
    assert LogosNodeRuntimeRegistry().peek_runtime_snapshot(99) is None


@pytest.mark.asyncio
async def test_peek_is_memoized_within_a_version():
    registry = _make_registry()

    first = registry.peek_runtime_snapshot(PROVIDER)
    second = registry.peek_runtime_snapshot(PROVIDER)
    third = registry.peek_runtime_snapshot(PROVIDER)

    assert first is not None
    assert first is second is third


@pytest.mark.asyncio
async def test_update_runtime_invalidates_memo():
    registry = _make_registry()
    before = registry.peek_runtime_snapshot(PROVIDER)
    assert before["runtime"] == {}

    await registry.update_runtime(PROVIDER, {"lanes": [{"model": "m"}]})
    after = registry.peek_runtime_snapshot(PROVIDER)

    assert after is not before
    assert after["runtime"] == {"lanes": [{"model": "m"}]}
    # The rebuilt snapshot is itself memoised again.
    assert after is registry.peek_runtime_snapshot(PROVIDER)


@pytest.mark.asyncio
async def test_append_event_invalidates_memo():
    registry = _make_registry()
    before = registry.peek_runtime_snapshot(PROVIDER)
    assert before["events"] == []

    await registry.append_event(PROVIDER, {"event": "request_finished", "seq": 1})
    after = registry.peek_runtime_snapshot(PROVIDER)

    assert after is not before
    assert after["events"] == [{"event": "request_finished", "seq": 1}]
    # The snapshot's events list is a copy: mutating it must not touch the
    # live session state (pre-existing contract, now per memo generation).
    after["events"].append({"event": "forged"})
    assert _session(registry).latest_events == [{"event": "request_finished", "seq": 1}]


@pytest.mark.asyncio
async def test_mark_heartbeat_invalidates_memo():
    registry = _make_registry()
    before = registry.peek_runtime_snapshot(PROVIDER)

    await registry.mark_heartbeat(PROVIDER)
    after = registry.peek_runtime_snapshot(PROVIDER)

    assert after is not before
    assert after["last_heartbeat"] == _session(registry).last_heartbeat.isoformat()


@pytest.mark.asyncio
async def test_detach_session_drops_memo_entry():
    """A fresh session on the same provider_id must not be served the
    previous session's cached dict (both start at snapshot_version 0, so
    only the pop keeps the memo honest)."""
    registry = _make_registry()
    old = registry.peek_runtime_snapshot(PROVIDER)
    assert old["worker_id"] == "worker-a"

    await registry.detach_session(PROVIDER)
    assert registry.peek_runtime_snapshot(PROVIDER) is None

    registry._sessions[PROVIDER] = ProviderSession(  # noqa: SLF001
        provider_id=PROVIDER, worker_id="worker-b", websocket=object()
    )
    fresh = registry.peek_runtime_snapshot(PROVIDER)
    assert fresh is not old
    assert fresh["worker_id"] == "worker-b"

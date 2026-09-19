"""Buffered lifecycle writes and the failure-path drain contract.

Most lifecycle fields are buffered and flushed in the single completion
UPDATE so the hot path stays cheap. Model / provider / scheduled_ts are
written eagerly as well — the live stats feed reads those columns while the
request is still in flight. The failure paths persist the row themselves, so
they drain the buffer via take_buffer and must fold the fields into their
own write for the row to keep the same content.
"""

from __future__ import annotations

import pytest
from tests.unit.monitoring.test_recorder import _make_recorder, _patch_prom

from logos.monitoring import recorder as recorder_module


@pytest.fixture(autouse=True)
def _isolated_state():
    """Tracked state and field buffers are module state shared across tests."""
    recorder_module._request_states.clear()
    recorder_module._field_buffers.clear()
    yield
    recorder_module._request_states.clear()
    recorder_module._field_buffers.clear()


def _full_lifecycle(recorder, request_id="req-buf"):
    recorder.record_enqueue(
        request_id=request_id,
        model_id=27,
        provider_id=12,
        initial_priority="normal",
        queue_depth=0,
        timeout_s=60,
    )
    recorder.record_scheduled(
        request_id=request_id,
        model_id=27,
        provider_id=13,  # scheduling overrides the enqueue-time guess
        priority_when_scheduled="high",
        queue_depth_at_schedule=2,
        provider_metrics={"available_vram_mb": 4096},
    )
    recorder.record_provider(request_id, 13)
    recorder.record_rate_limit_admission(request_id, admitted=True)


def test_completion_write_carries_the_buffered_union(monkeypatch):
    recorder, calls = _make_recorder(monkeypatch, {27: "m"}, {13: "p"})
    _patch_prom(monkeypatch)

    _full_lifecycle(recorder)
    assert len(calls) == 2  # eager live writes at enqueue + schedule
    recorder.record_complete(request_id="req-buf", result_status="success")

    assert len(calls) == 3
    call = calls[-1]
    assert call["model_id"] == 27
    # Last write wins on a collision, exactly like the sequential UPDATEs.
    assert call["provider_id"] == 13
    assert call["initial_priority"] == "normal"
    assert call["priority_when_scheduled"] == "high"
    assert call["queue_depth_at_schedule"] == 2
    assert call["available_vram_mb"] == 4096
    assert call["rate_limit_admitted"] is True
    assert call["result_status"] == "success"


def test_taking_the_buffer_drains_it_for_the_failure_write(monkeypatch):
    """_record_log_failure drains before discard and folds the fields into
    its own metrics UPDATE — the row must keep every buffered field."""
    recorder, calls = _make_recorder(monkeypatch, {27: "m"}, {13: "p"})
    _patch_prom(monkeypatch)

    _full_lifecycle(recorder)
    live_writes = list(calls)

    buffered = recorder.take_buffer("req-buf")
    recorder.discard("req-buf", "error")

    assert buffered == {
        "model_id": 27,
        "provider_id": 13,
        "initial_priority": "normal",
        "queue_depth_at_enqueue": 0,
        "timeout_s": 60,
        "priority_when_scheduled": "high",
        "queue_depth_at_schedule": 2,
        "scheduled_ts": buffered["scheduled_ts"],
        "available_vram_mb": 4096,
        "rate_limit_admitted": True,
    }
    # Drain/discard do not touch the DB; only the earlier live writes did.
    assert calls == live_writes
    assert len(live_writes) == 2
    # The buffer is empty after the drain: a double drain is a no-op.
    assert recorder.take_buffer("req-buf") == {}


def test_discard_without_a_drain_leaves_no_completion_write(monkeypatch):
    recorder, calls = _make_recorder(monkeypatch, {27: "m"}, {13: "p"})
    _patch_prom(monkeypatch)

    _full_lifecycle(recorder)
    live_writes = list(calls)
    recorder.discard("req-buf", "error")

    assert calls == live_writes


def test_complete_after_drain_writes_only_the_terminal_fields(monkeypatch):
    """A path that drained for its own failure write and then unwinds
    through record_completion must not re-emit the buffered fields."""
    recorder, calls = _make_recorder(monkeypatch, {27: "m"}, {13: "p"})
    _patch_prom(monkeypatch)

    _full_lifecycle(recorder)
    live_count = len(calls)
    recorder.take_buffer("req-buf")
    recorder.discard("req-buf", "error")
    recorder.record_complete(request_id="req-buf", result_status="error")

    assert len(calls) == live_count + 1
    call = calls[-1]
    assert call["result_status"] == "error"
    assert "initial_priority" not in call
    assert "rate_limit_admitted" not in call


def test_take_buffer_for_an_unknown_request_is_empty(monkeypatch):
    recorder, _ = _make_recorder(monkeypatch, {}, {})
    _patch_prom(monkeypatch)

    assert recorder.take_buffer("never-seen") == {}


def test_settle_and_take_returns_the_terminal_write_without_db(monkeypatch):
    """settle_and_take is the event-loop half of the split completion write:
    it settles the request and pops the buffer, but performs no DB write —
    the caller hands the dict to write_completion on the queue thread."""
    recorder, calls = _make_recorder(monkeypatch, {27: "m"}, {13: "p"})
    _patch_prom(monkeypatch)

    _full_lifecycle(recorder)
    live_count = len(calls)
    fields = recorder.settle_and_take("req-buf", "success", error_message=None)

    assert len(calls) == live_count  # settle_and_take itself does not write
    assert fields["result_status"] == "success"
    assert fields["provider_id"] == 13
    assert "request_complete_ts" in fields
    # The shared state is already finalised: nothing left in the buffer, and
    # the in-flight gauge is down.
    assert recorder_module._field_buffers == {}
    assert recorder_module._request_states == {}


def test_write_completion_writes_only_the_handover_dict(monkeypatch):
    """write_completion is the queue-thread half: it must touch no shared
    recorder state (the old bug: record_completion running on the write-queue
    thread popped the event loop's dicts — the stale sweep could then raise
    'dictionary changed size during iteration')."""
    recorder, calls = _make_recorder(monkeypatch, {27: "m"}, {13: "p"})
    _patch_prom(monkeypatch)

    # A live request on the event loop, exactly the interleaving the race
    # needs: the queue thread writes request A while the loop tracks B.
    _full_lifecycle(recorder)
    fields = recorder.settle_and_take("req-buf", "success")
    before = len(calls)
    recorder.record_enqueue(request_id="req-other", model_id=27, provider_id=13, initial_priority=None, queue_depth=0)
    assert len(calls) == before + 1  # eager live write for req-other

    recorder.write_completion("req-buf", fields)

    assert len(calls) == before + 2
    assert calls[-1] == {**fields, "request_id": "req-buf"}
    # The event-loop request is untouched by the queue-thread write.
    assert "req-other" in recorder_module._request_states
    assert recorder_module._field_buffers["req-other"]


def test_split_write_matches_record_complete(monkeypatch):
    """record_complete (direct callers, e.g. streaming) must produce the same
    DB write as settle_and_take + write_completion (queued sync path)."""
    recorder, calls = _make_recorder(monkeypatch, {27: "m"}, {13: "p"})
    _patch_prom(monkeypatch)

    _full_lifecycle(recorder)
    recorder.record_complete(request_id="req-buf", result_status="success", usage_tokens={"prompt_tokens": 3})
    direct = calls.pop()

    _full_lifecycle(recorder)
    fields = recorder.settle_and_take("req-buf", "success", usage_tokens={"prompt_tokens": 3})
    recorder.write_completion("req-buf", fields)
    split = calls.pop()

    # The two lifecycle runs stamp their own timestamps — drop both.
    for call in (direct, split):
        call.pop("request_complete_ts", None)
        call.pop("scheduled_ts", None)
    assert split == direct


def test_enqueue_writes_requested_model_for_queued_rows(monkeypatch):
    """Queued stats rows read model_id before completion — enqueue must land it."""
    recorder, calls = _make_recorder(monkeypatch, {27: "Qwen/Qwen3-8B"}, {12: "gpu-01"})
    _patch_prom(monkeypatch)

    recorder.record_enqueue(
        request_id="req-queued",
        model_id=27,
        provider_id=12,
        initial_priority="normal",
        queue_depth=4,
    )

    assert calls == [{"request_id": "req-queued", "model_id": 27, "provider_id": 12}]

"""Routing a request to a worker whose context window fits it.

The same model can be placed with very different windows on different workers,
so the widest one is only reachable if routing steers there. See
``_prefer_deployments_with_context_room`` in ``logos.main``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import logos as main_mod

NARROW_PROVIDER = 1
WIDE_PROVIDER = 2
MODEL_ID = 42
MODEL_NAME = "qwen-27b"


def _registry(windows: dict[int, int]) -> MagicMock:
    """A registry whose workers serve MODEL_NAME at the given windows."""
    registry = MagicMock()
    registry.active_provider_ids = lambda: list(windows)
    registry.peek_runtime_snapshot = lambda pid: {
        "runtime": {
            "lanes": [
                {
                    "model": MODEL_NAME,
                    "vllm": True,
                    "backend_metrics": {"max_model_len": windows[pid]},
                }
            ],
            "model_profiles": {},
        }
    }
    return registry


def _deployments(*provider_ids: int) -> list[dict]:
    return [{"provider_id": pid, "model_id": MODEL_ID, "type": "logosnode"} for pid in provider_ids]


def _payload(prompt_chars: int, max_tokens: int = 4096) -> dict:
    return {
        "model": MODEL_NAME,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": "x" * prompt_chars}],
    }


@pytest.fixture
def two_workers(monkeypatch):
    monkeypatch.setattr(
        main_mod,
        "_logosnode_registry",
        _registry({NARROW_PROVIDER: 33000, WIDE_PROVIDER: 262144}),
    )


def _filter(deployments, payload):
    return main_mod._prefer_deployments_with_context_room(deployments, payload, {MODEL_ID: MODEL_NAME})


def test_long_request_skips_the_narrow_worker(two_workers):
    # ~50k tokens of prompt: fits the 262144 worker, not the 33000 one.
    result = _filter(_deployments(NARROW_PROVIDER, WIDE_PROVIDER), _payload(150_000))
    assert [d["provider_id"] for d in result] == [WIDE_PROVIDER]


def test_short_request_keeps_both_workers(two_workers):
    """A short request must not be steered anywhere.

    Narrowing the candidate set for requests that fit everywhere would push all
    traffic onto one worker and undo the load balancing.
    """
    result = _filter(_deployments(NARROW_PROVIDER, WIDE_PROVIDER), _payload(400))
    assert [d["provider_id"] for d in result] == [NARROW_PROVIDER, WIDE_PROVIDER]


def test_falls_back_to_the_widest_when_nothing_fits(two_workers):
    """Too long for every worker: hand back the widest, not an empty list.

    Returning nothing would turn this into a 404 that names no model, hiding
    the real problem. The request fails upstream with the limit spelled out,
    exactly as it did before this filter existed.
    """
    result = _filter(_deployments(NARROW_PROVIDER, WIDE_PROVIDER), _payload(2_000_000))
    assert [d["provider_id"] for d in result] == [WIDE_PROVIDER]


def test_unknown_window_is_never_treated_as_narrow(monkeypatch):
    """A worker that reports no window keeps its place in the candidate list.

    Cloud providers and lanes that have not reported yet have no window; that
    is missing information, not evidence of a narrow one.
    """
    monkeypatch.setattr(main_mod, "_logosnode_registry", _registry({NARROW_PROVIDER: 33000}))
    deployments = _deployments(NARROW_PROVIDER) + [{"provider_id": 99, "model_id": MODEL_ID, "type": "azure"}]
    result = _filter(deployments, _payload(150_000))
    assert [d["provider_id"] for d in result] == [99]


def test_no_windows_known_at_all_changes_nothing(monkeypatch):
    registry = MagicMock()
    registry.active_provider_ids = lambda: []
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)
    deployments = _deployments(NARROW_PROVIDER, WIDE_PROVIDER)
    assert _filter(deployments, _payload(150_000)) == deployments


def test_unreadable_payload_changes_nothing(two_workers):
    deployments = _deployments(NARROW_PROVIDER, WIDE_PROVIDER)
    assert _filter(deployments, {"model": MODEL_NAME}) == deployments


def test_output_reservation_counts_against_the_window(two_workers):
    """Input and output share one budget upstream, so both have to fit.

    A prompt that fits on its own can still overflow once the reply it asked
    for is reserved — which is the failure this whole path exists to avoid.
    """
    # ~11000 prompt tokens. Plus a 4k reply and the margin that is 18k, which
    # fits the 33000 worker; plus a 20k reply it is 34k, which does not.
    small_reply = _filter(_deployments(NARROW_PROVIDER, WIDE_PROVIDER), _payload(33_000, 4096))
    assert NARROW_PROVIDER in [d["provider_id"] for d in small_reply]

    big_reply = _filter(_deployments(NARROW_PROVIDER, WIDE_PROVIDER), _payload(33_000, 20_000))
    assert [d["provider_id"] for d in big_reply] == [WIDE_PROVIDER]


@pytest.mark.asyncio
async def test_audio_uploads_are_left_alone(monkeypatch, two_workers):
    """A transcription hint is not a conversation.

    Whisper payloads carry a "prompt" field of a few words plus a file; sizing
    a context window from that says nothing useful, so the filter stays out.
    """
    monkeypatch.setattr(main_mod, "is_multipart_payload", lambda payload: True)
    called = False

    def _spy(*args, **kwargs):
        nonlocal called
        called = True
        return args[0]

    monkeypatch.setattr(main_mod, "_prefer_deployments_with_context_room", _spy)

    db = MagicMock()
    db.get_model.return_value = {"name": MODEL_NAME}
    monkeypatch.setattr(main_mod, "DBManager", lambda: _ctx(db))

    async def _allowed(provider_id, model_name):
        return True

    monkeypatch.setattr(main_mod._logosnode_registry, "is_model_allowed", _allowed)

    await main_mod._filter_logosnode_deployments(
        _deployments(NARROW_PROVIDER), payload={"file": b"...", "prompt": "hi"}
    )
    assert called is False


class _ctx:
    """Minimal stand-in for the DBManager context manager."""

    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self._db

    def __exit__(self, *exc):
        return False

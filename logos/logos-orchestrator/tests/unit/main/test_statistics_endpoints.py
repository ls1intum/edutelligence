import pytest

from logos.logosnode_snapshot import _build_logosnode_scheduler_signals


def test_scheduler_signals_mtp_acceptance_is_token_weighted_across_lanes() -> None:
    """Per-model MTP rate sums the draft/accepted counters, it is NOT the
    unweighted mean of per-lane rates (regression for the CodeRabbit review)."""

    def _lane(lane_id: str, draft: float, accepted: float) -> dict:
        return {
            "lane_id": lane_id,
            "model": "mtp-model",
            "vllm": True,
            "runtime_state": "running",
            "active_requests": 0,
            "effective_vram_mb": 8000.0,
            "backend_metrics": {
                "engine": "vllm",
                "mtp_acceptance_rate": (accepted / draft) if draft > 0 else None,
                "mtp_draft_tokens_total": draft,
                "mtp_accepted_tokens_total": accepted,
            },
        }

    # Lane A: perfect acceptance but a single draft token.
    # Lane B: zero acceptance over 10,000 draft tokens.
    runtime = {
        "timestamp": "2026-03-16T18:00:00Z",
        "transport": {"connected": True},
        "devices": {},
        "capacity": {},
        "lanes": [
            _lane("lane-a", draft=1, accepted=1),
            _lane("lane-b", draft=10_000, accepted=0),
        ],
    }

    signals = _build_logosnode_scheduler_signals(runtime)
    model = signals["models"]["mtp-model"]

    # Token-weighted: 1 accepted / 10,001 draft. The unweighted lane-rate
    # mean would be 0.5 — exactly the misstatement this regression guards.
    assert model["mtp_acceptance_rate_avg"] == pytest.approx(1 / 10_001)

    # The per-lane signal still carries each lane's own rate.
    assert signals["lanes"]["lane-a"]["mtp_acceptance_rate"] == pytest.approx(1.0)
    assert signals["lanes"]["lane-b"]["mtp_acceptance_rate"] == pytest.approx(0.0)


def test_scheduler_signals_mtp_acceptance_none_without_spec_decode() -> None:
    """Lanes without speculative decoding leave the per-model rate unset."""
    runtime = {
        "timestamp": "2026-03-16T18:00:00Z",
        "transport": {"connected": True},
        "devices": {},
        "capacity": {},
        "lanes": [
            {
                "lane_id": "lane-a",
                "model": "plain-model",
                "vllm": True,
                "runtime_state": "loaded",
                "active_requests": 0,
                "effective_vram_mb": 8000.0,
                "backend_metrics": {"engine": "vllm", "prefix_cache_hit_rate": 0.3},
            }
        ],
    }

    signals = _build_logosnode_scheduler_signals(runtime)
    assert signals["models"]["plain-model"]["mtp_acceptance_rate_avg"] is None
    assert signals["models"]["plain-model"]["prefix_cache_hit_rate_avg"] == pytest.approx(0.3)


# ── Host RAM in the provider signals ─────────────────────────────────────────
# The statistics page shows host RAM the same way it shows VRAM. The numbers
# travel on the worker's runtime host_memory summary, present on every
# heartbeat on Linux and all-zero with source="unavailable" elsewhere.


def test_scheduler_signals_report_host_ram_from_the_runtime_summary() -> None:
    runtime = {
        "timestamp": "2026-03-16T18:00:00Z",
        "transport": {"connected": True},
        "devices": {},
        "capacity": {},
        "lanes": [],
        "host_memory": {
            "source": "proc-meminfo",
            "total_mb": 516096.0,
            "available_mb": 312048.0,
            "used_mb": 204048.0,
        },
    }

    signals = _build_logosnode_scheduler_signals(runtime)
    assert signals["provider"]["host_ram_total_mb"] == 516096.0
    assert signals["provider"]["host_ram_used_mb"] == 204048.0
    assert signals["provider"]["host_ram_available_mb"] == 312048.0


def test_scheduler_signals_leave_host_ram_unset_without_a_summary() -> None:
    """A runtime without host_memory (an older worker) must not fabricate
    zeros — the UI has to tell "not reported" apart from a host that
    genuinely measured 0 MB free."""
    runtime = {
        "timestamp": "2026-03-16T18:00:00Z",
        "transport": {"connected": True},
        "devices": {},
        "capacity": {},
        "lanes": [],
    }

    signals = _build_logosnode_scheduler_signals(runtime)
    assert signals["provider"]["host_ram_total_mb"] is None
    assert signals["provider"]["host_ram_used_mb"] is None
    assert signals["provider"]["host_ram_available_mb"] is None


# ── Per-lane context window ──────────────────────────────────────────────────
# The statistics page shows the window each lane is serving at. It has to travel
# on the lane, not the model: the planner sizes every lane against the KV cache
# it could get, so two lanes of one model routinely differ.


def _ctx_runtime(lane: dict, profiles: dict | None = None) -> dict:
    return {
        "timestamp": "2026-03-16T18:00:00Z",
        "transport": {"connected": True},
        "devices": {},
        "capacity": {},
        "lanes": [lane],
        "model_profiles": profiles or {},
    }


def test_lane_signal_reports_the_window_vllm_is_running_at() -> None:
    signals = _build_logosnode_scheduler_signals(
        _ctx_runtime(
            {
                "lane_id": "lane-a",
                "model": "big-model",
                "vllm": True,
                "runtime_state": "running",
                "active_requests": 0,
                "effective_vram_mb": 90000.0,
                "backend_metrics": {"engine": "vllm", "max_model_len": 111200},
            }
        )
    )
    assert signals["lanes"]["lane-a"]["max_model_len"] == 111200


def test_two_lanes_of_one_model_report_their_own_windows() -> None:
    """The whole reason this is per lane and not per model."""
    runtime = _ctx_runtime({}, {})
    runtime["lanes"] = [
        {
            "lane_id": "roomy",
            "model": "same-model",
            "vllm": True,
            "runtime_state": "running",
            "active_requests": 0,
            "effective_vram_mb": 90000.0,
            "backend_metrics": {"engine": "vllm", "max_model_len": 262144},
        },
        {
            "lane_id": "cramped",
            "model": "same-model",
            "vllm": True,
            "runtime_state": "running",
            "active_requests": 0,
            "effective_vram_mb": 20000.0,
            "backend_metrics": {"engine": "vllm", "max_model_len": 32768},
        },
    ]

    signals = _build_logosnode_scheduler_signals(runtime)

    assert signals["lanes"]["roomy"]["max_model_len"] == 262144
    assert signals["lanes"]["cramped"]["max_model_len"] == 32768


def test_lane_signal_falls_back_to_the_calibrated_profile() -> None:
    """A vLLM lane started without --max-model-len takes the calibrated value,
    so the number is not on the lane itself."""
    signals = _build_logosnode_scheduler_signals(
        _ctx_runtime(
            {
                "lane_id": "lane-a",
                "model": "calibrated-model",
                "vllm": True,
                "runtime_state": "loaded",
                "active_requests": 0,
                "effective_vram_mb": 8000.0,
                "backend_metrics": {"engine": "vllm"},
            },
            {"calibrated-model": {"calibration_max_model_len": 40960}},
        )
    )
    assert signals["lanes"]["lane-a"]["max_model_len"] == 40960


def test_lane_signal_reports_the_configured_window_when_the_engine_reports_none() -> None:
    """A vLLM lane whose engine has not reported a window yet falls back to
    the configured lane context_length (4096 is the shared "unset" sentinel
    and is skipped)."""
    signals = _build_logosnode_scheduler_signals(
        _ctx_runtime(
            {
                "lane_id": "lane-a",
                "model": "configured-model",
                "vllm": True,
                "runtime_state": "loaded",
                "active_requests": 0,
                "effective_vram_mb": 8000.0,
                "context_length": 8192,
            }
        )
    )
    assert signals["lanes"]["lane-a"]["max_model_len"] == 8192


def test_lane_signal_omits_a_window_it_cannot_derive() -> None:
    """None rather than 0: the row leaves the badge off instead of claiming a
    size vLLM picked for itself and never reported."""
    signals = _build_logosnode_scheduler_signals(
        _ctx_runtime(
            {
                "lane_id": "lane-a",
                "model": "unknown-model",
                "vllm": True,
                "runtime_state": "loaded",
                "active_requests": 0,
                "effective_vram_mb": 8000.0,
                "backend_metrics": {"engine": "vllm"},
            }
        )
    )
    assert signals["lanes"]["lane-a"]["max_model_len"] is None

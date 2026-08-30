"""CalibrationOrchestrator GPU-slice eligibility (issue #592).

On a heterogeneous node (e.g. 3 GPUs) the calibration probe only uses a
power-of-two slice of the GPUs — the largest slice, ``{0..tp-1}``. A lane that
is busy only on the *leftover* GPU(s) outside that slice does not touch the
probe, so it must not block the orchestrator from starting a session.

These tests pin down three helpers that implement that rule:

* ``_calibration_gpu_subset`` — derive the slice from the worker's reported
  NVIDIA GPU count (the same count the worker uses to pin its probe).
* ``_lane_touches_subset`` — does a lane's ``gpu_devices`` selector intersect
  the slice? (blank / "all" spans every GPU, "none" spans none).
* ``_provider_has_active_requests`` — a worker is only "busy" when a lane that
  touches the slice has active requests / queued demand. When the slice cannot
  be determined (no telemetry, no known GPU count) the old conservative
  behaviour applies: any busy lane blocks.

The orchestrator is exercised the same way the neighbouring tests do it —
``CalibrationOrchestrator.__new__`` plus fake ``_registry`` / ``_facade`` — so
we test the pure decision logic without a live registry or a tick loop.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from logos.capacity.calibration_orchestrator import CalibrationOrchestrator

# ---------------------------------------------------------------------------
# Fakes / helpers
# ---------------------------------------------------------------------------


def _nvidia_snapshot(n_gpus: int, *, kinds=None) -> dict:
    """A runtime snapshot exposing *n_gpus* devices.

    ``kinds`` optionally overrides the ``kind`` per index (a device without a
    ``kind`` key is treated as NVIDIA — matching how real snapshots look).
    """
    devices = []
    for i in range(n_gpus):
        dev = {"device_id": f"GPU-{i}", "extra": {"index": i}}
        if kinds is not None and kinds[i] is not None:
            dev["kind"] = kinds[i]
        devices.append(dev)
    return {"runtime": {"lanes": [], "devices": {"devices": devices}}}


def _signal(*, active_requests=0, queue_waiting=0.0, gpu_devices=""):
    """A lane signal as the orchestrator reads it (only these attrs matter)."""
    sig = MagicMock()
    sig.active_requests = active_requests
    sig.queue_waiting = queue_waiting
    sig.gpu_devices = gpu_devices
    return sig


_USE_DEFAULT_SNAPSHOT = object()


def _orch(n_gpus, signals, *, snapshot=_USE_DEFAULT_SNAPSHOT, facade_raises=False):
    """A CalibrationOrchestrator wired with a fake registry and facade.

    ``snapshot`` defaults to a snapshot with *n_gpus* NVIDIA GPUs; pass an
    explicit dict (or ``None`` for "no snapshot") to override it.
    """
    orch = CalibrationOrchestrator.__new__(CalibrationOrchestrator)
    registry = MagicMock()
    registry.peek_runtime_snapshot.return_value = (
        _nvidia_snapshot(n_gpus) if snapshot is _USE_DEFAULT_SNAPSHOT else snapshot
    )
    facade = MagicMock()
    if facade_raises:
        facade.get_all_provider_lane_signals.side_effect = RuntimeError("telemetry down")
    else:
        facade.get_all_provider_lane_signals.return_value = signals
    orch._registry = registry
    orch._facade = facade
    return orch


# ---------------------------------------------------------------------------
# _calibration_gpu_subset
# ---------------------------------------------------------------------------


def test_subset_is_largest_power_of_two_slice_3gpu():
    """3 GPUs → the calibration holds {0, 1} and GPU 2 is the leftover."""
    orch = _orch(3, [])
    assert orch._calibration_gpu_subset(7) == frozenset({0, 1})


def test_subset_is_largest_power_of_two_slice_5gpu():
    """5 GPUs → the calibration holds {0, 1, 2, 3} and GPU 4 is the leftover."""
    orch = _orch(5, [])
    assert orch._calibration_gpu_subset(7) == frozenset({0, 1, 2, 3})


def test_subset_single_gpu():
    orch = _orch(1, [])
    assert orch._calibration_gpu_subset(7) == frozenset({0})


def test_subset_8gpu_is_the_whole_node():
    orch = _orch(8, [])
    assert orch._calibration_gpu_subset(7) == frozenset(set(range(8)))


def test_subset_empty_when_no_snapshot():
    orch = _orch(3, [], snapshot=None)
    assert orch._calibration_gpu_subset(7) == frozenset()


def test_subset_empty_when_devices_missing():
    orch = _orch(3, [], snapshot={"runtime": {}})
    assert orch._calibration_gpu_subset(7) == frozenset()


def test_subset_counts_only_nvidia_devices():
    """2 NVIDIA + 1 AMD → the probe slice is sized from the NVIDIA count only."""
    orch = _orch(3, [], snapshot=_nvidia_snapshot(3, kinds=[None, None, "amd"]))
    assert orch._calibration_gpu_subset(7) == frozenset({0, 1})


def test_subset_empty_when_indexes_malformed():
    """A device whose ``extra.index`` is not an int cannot be counted."""
    snap = {
        "runtime": {
            "devices": {
                "devices": [{"device_id": "GPU-0", "extra": {"index": "not-an-int"}}],
            },
        },
    }
    orch = _orch(1, [], snapshot=snap)
    assert orch._calibration_gpu_subset(7) == frozenset()


# ---------------------------------------------------------------------------
# _lane_touches_subset
# ---------------------------------------------------------------------------


def _touch(gpu_devices, subset):
    return CalibrationOrchestrator._lane_touches_subset(gpu_devices, subset)


def test_touch_blank_spans_all_gpus():
    assert _touch("", frozenset({0, 1})) is True
    assert _touch(None, frozenset({0, 1})) is True


def test_touch_all_keyword_spans_all_gpus():
    assert _touch("all", frozenset({0, 1})) is True
    assert _touch(" ALL ", frozenset({0, 1})) is True


def test_touch_none_keyword_spans_nothing():
    assert _touch("none", frozenset({0, 1})) is False


def test_touch_explicit_selector_by_intersection():
    assert _touch("0", frozenset({0, 1})) is True
    assert _touch("2", frozenset({0, 1})) is False
    assert _touch("0,2", frozenset({0, 1})) is True
    assert _touch("2,3", frozenset({0, 1})) is False
    assert _touch("0, 1", frozenset({0, 1})) is True


# ---------------------------------------------------------------------------
# _provider_has_active_requests
# ---------------------------------------------------------------------------


def test_leftover_gpu_lane_does_not_block():
    """Acceptance #3: a lane busy only on the leftover GPU (2) does not block
    a calibration of the {0, 1} slice on a 3-GPU worker."""
    orch = _orch(3, [_signal(active_requests=4, gpu_devices="2")])
    assert orch._provider_has_active_requests(7) is False


def test_slice_gpu_lane_blocks():
    orch = _orch(3, [_signal(active_requests=4, gpu_devices="0")])
    assert orch._provider_has_active_requests(7) is True


def test_all_selector_lane_blocks():
    orch = _orch(3, [_signal(active_requests=4, gpu_devices="all")])
    assert orch._provider_has_active_requests(7) is True


def test_blank_selector_lane_blocks():
    orch = _orch(3, [_signal(active_requests=4, gpu_devices="")])
    assert orch._provider_has_active_requests(7) is True


def test_partial_slice_lane_blocks():
    """A lane on "1,2" touches the slice via GPU 1, so it still blocks."""
    orch = _orch(3, [_signal(active_requests=4, gpu_devices="1,2")])
    assert orch._provider_has_active_requests(7) is True


def test_idle_lanes_do_not_block():
    orch = _orch(3, [_signal(active_requests=0, gpu_devices="0"), _signal(active_requests=0, gpu_devices="2")])
    assert orch._provider_has_active_requests(7) is False


def test_queue_waiting_on_slice_blocks():
    """active_requests=0 but queue_waiting>0 counts as busy on the slice."""
    orch = _orch(3, [_signal(active_requests=0, queue_waiting=2.0, gpu_devices="1")])
    assert orch._provider_has_active_requests(7) is True


def test_mixed_idle_slice_and_busy_leftover():
    """One idle slice lane plus one busy leftover lane → still not blocking."""
    orch = _orch(3, [_signal(active_requests=0, gpu_devices="0"), _signal(active_requests=3, gpu_devices="2")])
    assert orch._provider_has_active_requests(7) is False


def test_unknown_subset_falls_back_to_conservative():
    """No snapshot → slice unknown → any busy lane blocks (previous behaviour)."""
    orch = _orch(3, [_signal(active_requests=4, gpu_devices="2")], snapshot=None)
    assert orch._provider_has_active_requests(7) is True


def test_facade_exception_is_conservative():
    """Telemetry unavailable → assume busy rather than interrupting work."""
    orch = _orch(3, [], facade_raises=True)
    assert orch._provider_has_active_requests(7) is True

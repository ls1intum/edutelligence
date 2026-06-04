"""
Replace the logos package with logos.main in sys.modules.

This makes `import logos as main` return logos.main directly, so that
monkeypatch.setattr(logos, "_pipeline", mock) patches logos.main.__dict__
and functions whose globals are logos.main.__dict__ see the patched values.

Symbols not in logos.main's namespace are injected before the replacement.
"""

import sys

import logos.main as _m  # triggers full initialization
from logos.auth import AuthContext  # noqa: F401

# ── Symbols not imported into logos.main's namespace ─────────────────────────


_m.AuthContext = AuthContext

from logos.dbutils.dbmodules import ThresholdLevel  # noqa: F401

_m.ThresholdLevel = ThresholdLevel

from logos.pipeline.context_resolver import ExecutionContext  # noqa: F401

_m.ExecutionContext = ExecutionContext

from logos.pipeline.scheduler_interface import (  # noqa: F401
    SchedulingRequest,
    SchedulingResult,
)

_m.SchedulingRequest = SchedulingRequest
_m.SchedulingResult = SchedulingResult

from logos.pipeline.ettft_estimator import CLOUD_LOW_HEADROOM_S  # noqa: F401
from logos.pipeline.ettft_estimator import (
    CLOUD_OVERHEAD_S,
    CORRECTION_STRENGTH,
    MIN_SPAN_FLOOR,
    NORMALIZATION_HORIZON_S,
    EttftEstimate,
    ReadinessTier,
    compute_corrected_score,
    compute_weight_span,
    estimate_ettft_azure,
    estimate_ettft_cloud,
)

_m.CLOUD_LOW_HEADROOM_S = CLOUD_LOW_HEADROOM_S
_m.CLOUD_OVERHEAD_S = CLOUD_OVERHEAD_S
_m.CORRECTION_STRENGTH = CORRECTION_STRENGTH
_m.EttftEstimate = EttftEstimate
_m.MIN_SPAN_FLOOR = MIN_SPAN_FLOOR
_m.NORMALIZATION_HORIZON_S = NORMALIZATION_HORIZON_S
_m.ReadinessTier = ReadinessTier
_m.compute_corrected_score = compute_corrected_score
_m.compute_weight_span = compute_weight_span
_m.estimate_ettft_azure = estimate_ettft_azure
_m.estimate_ettft_cloud = estimate_ettft_cloud

from logos.sdi.models import AzureCapacity  # noqa: F401
from logos.sdi.models import LaneSchedulerSignals, ModelProfile, ModelSchedulerView

_m.AzureCapacity = AzureCapacity
_m.LaneSchedulerSignals = LaneSchedulerSignals
_m.ModelProfile = ModelProfile
_m.ModelSchedulerView = ModelSchedulerView

from logos.capacity.vram_ledger import VRAMLedger  # noqa: F401

_m.VRAMLedger = VRAMLedger

from logos.capacity.lane_comparator import best_lane, lane_sort_key  # noqa: F401

_m.best_lane = best_lane
_m.lane_sort_key = lane_sort_key

from logos.monitoring.recorder import MonitoringRecorder  # noqa: F401

_m.MonitoringRecorder = MonitoringRecorder

from logos.terminal_logging import format_bytes, format_memory_usage  # noqa: F401

_m.format_bytes = format_bytes
_m.format_memory_usage = format_memory_usage

from logos.logosnode_registry import _lane_log_snapshot  # noqa: F401
from logos.logosnode_registry import _render_lane_diff, _render_lane_summary

_m._lane_log_snapshot = _lane_log_snapshot
_m._render_lane_diff = _render_lane_diff
_m._render_lane_summary = _render_lane_summary

# ── Expose sub-packages as attributes of logos.main ──────────────────────────
# monkeypatch.setattr("logos.sdi.X.Y", ...) traverses logos → logos.main → .sdi → …
# These sub-packages are already in sys.modules (imported above via logos.main),
# but logos.main itself has no attribute for them — add them explicitly.

import logos.pipeline as _pipeline_pkg  # noqa: E402
import logos.responses as _responses_mod  # noqa: E402
import logos.sdi as _sdi_pkg  # noqa: E402

_m.sdi = _sdi_pkg
_m.pipeline = _pipeline_pkg
_m.responses = _responses_mod

# ── Replace logos package with logos.main ────────────────────────────────────
# Preserve __path__ so `from logos.X import Y` submodule imports still work.

_m.__path__ = __path__
_m.__package__ = __package__
sys.modules[__name__] = _m

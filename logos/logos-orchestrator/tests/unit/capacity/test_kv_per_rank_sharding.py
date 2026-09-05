"""Regression tests for _estimate_kv_mb's per-rank KV budget at TP > 1.

kv_per_token_bytes on a ModelProfile is the WHOLE-MODEL footprint (every KV
head), documented that way by the worker's HF precheck (hf_model_info.py).
But every downstream consumer of _estimate_kv_mb's return value treats it as
a PER-RANK budget: it becomes the vLLM --kv-cache-memory-bytes string, which
gets applied on EACH of the tp GPUs a lane occupies (see
_estimate_available_for_kv_mb's own docstring). Without sharding the
whole-model figure down to one rank's share first, a tp=4 lane would get
~4x its intended KV budget applied on every GPU, wasting VRAM or (combined
with other lanes) causing otherwise-fitting placements to fail.

The fix mirrors the worker precheck's own head-sharding rule (see
hf_model_info.min_feasible_tp / _fits_at_tp): heads_per_rank = max(1,
num_key_value_heads // tp), and the per-rank share is
whole_model_kv_mb * heads_per_rank / num_key_value_heads.
"""

from __future__ import annotations

from logos.capacity.capacity_planner import CapacityPlanner
from logos.sdi.models import ModelProfile


def _hf_profile(*, kv_per_token_bytes: int, num_key_value_heads: int | None, max_context_length: int = 8192):
    return ModelProfile(
        model_name="test/model",
        engine="vllm",
        base_residency_mb=4000.0,
        residency_source="hf",
        kv_per_token_bytes=kv_per_token_bytes,
        num_key_value_heads=num_key_value_heads,
        max_context_length=max_context_length,
    )


def _make_planner() -> CapacityPlanner:
    return CapacityPlanner(logosnode_facade=None, logosnode_registry=None, demand_tracker=None)


def test_estimate_kv_mb_tp1_unaffected_by_head_count():
    """At tp=1 (the default), the whole-model figure IS the per-rank
    figure — no sharding needed, regardless of head count."""
    planner = _make_planner()
    profile = _hf_profile(kv_per_token_bytes=2 * 32 * 8 * 128 * 2, num_key_value_heads=8)
    whole_model_mb = planner._estimate_kv_mb(profile)  # noqa: SLF001
    assert planner._estimate_kv_mb(profile, tp=1) == whole_model_mb  # noqa: SLF001


def test_estimate_kv_mb_shards_by_kv_heads_at_tp_greater_than_one():
    """Regression: at tp=4 with 8 KV heads, each rank gets 2 heads
    (8 // 4) — a quarter of the whole-model figure, not the whole thing."""
    planner = _make_planner()
    profile = _hf_profile(kv_per_token_bytes=2 * 32 * 8 * 128 * 2, num_key_value_heads=8)
    whole_model_mb = planner._estimate_kv_mb(profile, tp=1)  # noqa: SLF001
    per_rank_mb = planner._estimate_kv_mb(profile, tp=4)  # noqa: SLF001
    assert per_rank_mb == whole_model_mb / 4


def test_estimate_kv_mb_replicates_when_kv_heads_fewer_than_tp():
    """GQA models can have very few KV heads (e.g. 8). At tp=16 > heads,
    vLLM replicates rather than shards further — heads_per_rank = max(1,
    8 // 16) = 1, so each rank still gets 1/8th, not 1/16th."""
    planner = _make_planner()
    profile = _hf_profile(kv_per_token_bytes=2 * 32 * 8 * 128 * 2, num_key_value_heads=8)
    whole_model_mb = planner._estimate_kv_mb(profile, tp=1)  # noqa: SLF001
    per_rank_mb = planner._estimate_kv_mb(profile, tp=16)  # noqa: SLF001
    assert per_rank_mb == whole_model_mb / 8


def test_estimate_kv_mb_leaves_unsharded_when_geometry_unknown():
    """Legacy profiles predating num_key_value_heads have no geometry to
    shard by — left unchanged rather than guessing (fail open, matching
    the pre-fix behaviour for these until they're re-prechecked)."""
    planner = _make_planner()
    profile = _hf_profile(kv_per_token_bytes=2 * 32 * 8 * 128 * 2, num_key_value_heads=None)
    whole_model_mb = planner._estimate_kv_mb(profile, tp=1)  # noqa: SLF001
    assert planner._estimate_kv_mb(profile, tp=4) == whole_model_mb  # noqa: SLF001


def test_estimate_kv_mb_observed_kv_budget_already_per_rank_unaffected_by_tp():
    """Priority-1 path (kv_budget_mb, an observed kv_cache_memory_bytes
    from a previous load) is already per-rank — tp must not touch it."""
    planner = _make_planner()
    profile = ModelProfile(
        model_name="test/model",
        engine="vllm",
        base_residency_mb=4000.0,
        kv_budget_mb=2048.0,
        kv_per_token_bytes=999999,  # would dominate if the priority chain were wrong
        num_key_value_heads=8,
    )
    assert planner._estimate_kv_mb(profile, tp=4) == 2048.0  # noqa: SLF001


def test_estimate_kv_mb_fallback_base_residency_divided_by_tp():
    """Priority-3 last-resort fallback (base_residency-derived, used only
    pre-HF-fetch) has no head geometry to shard by, but base_residency is
    itself a whole-lane total (see _estimate_available_for_kv_mb) — split
    evenly across ranks as the best available approximation."""
    planner = _make_planner()
    profile = ModelProfile(model_name="test/model", engine="vllm", base_residency_mb=4000.0)
    tp1 = planner._estimate_kv_mb(profile, tp=1)  # noqa: SLF001
    tp4 = planner._estimate_kv_mb(profile, tp=4)  # noqa: SLF001
    assert tp1 == 4000.0 * CapacityPlanner.KV_CACHE_HEADROOM_RATIO
    assert tp4 == tp1 / 4


def test_compute_kv_cache_bytes_shards_legacy_profile_at_tp():
    """End-to-end: _compute_kv_cache_bytes (the function whose return value
    is sent to vLLM as --kv-cache-memory-bytes, a per-rank flag) must
    reflect the sharded, not whole-model, figure for a legacy (no
    calibrated envelope) profile at tp > 1."""
    planner = _make_planner()
    profile = _hf_profile(kv_per_token_bytes=2 * 32 * 8 * 128 * 2, num_key_value_heads=8)
    tp1_str = planner._compute_kv_cache_bytes(profile, tp=1)  # noqa: SLF001
    tp4_str = planner._compute_kv_cache_bytes(profile, tp=4)  # noqa: SLF001
    tp1_mb = CapacityPlanner._parse_kv_cache_to_mb(tp1_str)
    tp4_mb = CapacityPlanner._parse_kv_cache_to_mb(tp4_str)
    assert tp4_mb == tp1_mb / 4


def test_estimate_model_loaded_vram_totals_kv_back_across_ranks():
    """_estimate_model_loaded_vram feeds every caller's comparison against
    a node-wide available_vram_mb (summed across all GPUs — see gpu.py's
    free_memory_mb). _estimate_kv_mb returns a PER-RANK budget, so this
    must multiply it back by tp to reconstruct the total KV memory vLLM
    actually reserves across all tp GPUs — not just the single rank's
    share, which would silently under-count the real footprint.

    At tp=4 with 8 KV heads (divides evenly), each rank holds 1/4 of the
    whole-model KV figure, but there are 4 ranks — the total is unchanged
    from tp=1, not smaller."""
    planner = _make_planner()
    narrow = _hf_profile(kv_per_token_bytes=2 * 32 * 8 * 128 * 2, num_key_value_heads=8)
    wide = _hf_profile(kv_per_token_bytes=2 * 32 * 8 * 128 * 2, num_key_value_heads=8)
    wide.tensor_parallel_size = 4
    assert planner._estimate_model_loaded_vram(wide) == planner._estimate_model_loaded_vram(narrow)  # noqa: SLF001


def test_estimate_model_loaded_vram_grows_when_kv_heads_replicated():
    """At tp > num_key_value_heads, vLLM replicates KV heads onto the extra
    ranks instead of sharding further, so the total KV memory grows with
    tp — the whole-lane estimate must reflect that growth, not shrink."""
    planner = _make_planner()
    narrow = _hf_profile(kv_per_token_bytes=2 * 32 * 8 * 128 * 2, num_key_value_heads=8)
    wide = _hf_profile(kv_per_token_bytes=2 * 32 * 8 * 128 * 2, num_key_value_heads=8)
    wide.tensor_parallel_size = 16
    assert planner._estimate_model_loaded_vram(wide) > planner._estimate_model_loaded_vram(narrow)  # noqa: SLF001

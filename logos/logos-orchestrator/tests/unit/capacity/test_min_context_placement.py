"""The context floor a lane has to clear to be worth placing.

Without a floor the planner takes whatever window fits the free KV cache, so
the same model ends up serving its full context on a roomy node and a fraction
of that on a busy one. Since the API can only promise the smallest window
across the cluster, the narrow lane is what every client is told the model can
do. See ``_min_context_tokens`` / ``_passes_minimum_load_feasibility``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from logos.capacity.capacity_planner import (
    DEFAULT_MIN_CONTEXT_FRACTION,
    CapacityPlanner,
    _initial_min_context_fraction,
    _initial_min_context_overrides,
)
from logos.sdi.models import ModelProfile


def _planner(fraction: float, overrides: dict[str, float] | None = None) -> CapacityPlanner:
    planner = CapacityPlanner.__new__(CapacityPlanner)
    planner._min_context_fraction = fraction
    planner._min_context_fraction_overrides = overrides or {}
    return planner


def _profile(
    *,
    native: int | None = None,
    pairs: list[dict] | None = None,
    name: str = "qwen/qwen3.8-27b",
) -> ModelProfile:
    return ModelProfile(
        model_name=name,
        engine="vllm",
        max_context_length=native,
        kv_cache_to_max_model_len_pairs=pairs,
    )


class TestNativeContextLength:
    def test_prefers_the_reported_context_length(self):
        assert CapacityPlanner._native_context_length(_profile(native=262144)) == 262144

    def test_falls_back_to_the_widest_calibrated_point(self):
        """Calibration is the only source when the model's own limit is absent.

        The widest window any KV point reached is what the model serves once it
        gets the cache it wants, which is the number the floor is a share of.
        """
        profile = _profile(
            native=None,
            pairs=[
                {"kv_mb": 1024, "max_model_len": 33000},
                {"kv_mb": 8192, "max_model_len": 131072},
            ],
        )
        assert CapacityPlanner._native_context_length(profile) == 131072

    def test_zero_when_nothing_is_known(self):
        assert CapacityPlanner._native_context_length(_profile()) == 0
        assert CapacityPlanner._native_context_length(None) == 0


class TestMinContextTokens:
    def test_share_of_the_native_length(self):
        assert _planner(0.5)._min_context_tokens(_profile(native=262144)) == 131072

    def test_zero_disables_the_floor(self):
        assert _planner(0.0)._min_context_tokens(_profile(native=262144)) == 0

    def test_per_model_override_wins(self):
        """Operators need "full context or nothing" for some models only.

        A coding assistant model is useless at a fraction of its window, while
        a small chat model is fine anywhere — one global number cannot say both.
        """
        planner = _planner(0.5, {"qwen/qwen3.8-27b": 1.0})
        assert planner._min_context_tokens(_profile(native=262144)) == 262144
        assert planner._min_context_tokens(_profile(native=262144, name="other/model")) == 131072

    def test_unknown_context_length_is_never_blocked(self):
        """The floor stops the planner choosing narrow, not uncalibrated loads.

        A model whose context length nobody reported has no share to take, so
        gating on it would keep the model off the cluster entirely.
        """
        assert _planner(1.0)._min_context_tokens(_profile()) == 0


class TestFeasibilityGate:
    """``_passes_minimum_load_feasibility`` with the floor applied."""

    def _gate(self, planner: CapacityPlanner, profile, available_for_kv: float | None):
        # Stub out the VRAM arithmetic: this test is about the context floor,
        # and the memory path has its own tests.
        planner._estimate_model_loaded_vram = lambda p: 1000.0
        planner._estimate_available_for_kv_mb = lambda p, c, pid, tp: available_for_kv
        planner._check_per_gpu_feasibility = lambda *a, **kw: True
        planner.get_pending_vram_mb = lambda pid: 0.0
        capacity = SimpleNamespace(available_vram_mb=80_000.0)
        return planner._passes_minimum_load_feasibility(profile.model_name, profile, capacity, provider_id=1)

    def _calibrated(self, pairs: list[dict], native: int) -> ModelProfile:
        profile = _profile(native=native, pairs=pairs)
        profile.residency_source = "calibrated"
        profile.base_residency_mb = 1000.0
        return profile

    def test_defers_when_only_a_narrow_point_fits(self):
        """Room for a narrow lane but not a useful one → wait for VRAM.

        Placing it would drag the model's advertised window down cluster-wide
        for as long as the lane lives.
        """
        profile = self._calibrated(
            [{"kv_mb": 1024, "max_model_len": 33000}, {"kv_mb": 8192, "max_model_len": 262144}],
            native=262144,
        )
        assert self._gate(_planner(0.5), profile, available_for_kv=2000.0) is False

    def test_places_when_a_wide_enough_point_fits(self):
        profile = self._calibrated(
            [{"kv_mb": 1024, "max_model_len": 33000}, {"kv_mb": 8192, "max_model_len": 262144}],
            native=262144,
        )
        assert self._gate(_planner(0.5), profile, available_for_kv=9000.0) is True

    def test_floor_off_keeps_the_old_behaviour(self):
        profile = self._calibrated(
            [{"kv_mb": 1024, "max_model_len": 33000}, {"kv_mb": 8192, "max_model_len": 262144}],
            native=262144,
        )
        assert self._gate(_planner(0.0), profile, available_for_kv=2000.0) is True

    def test_refuses_when_no_point_can_ever_reach_the_floor(self):
        """Nothing freeing up will help, so say so instead of retrying forever.

        This is the "full context or nothing" case on a node whose calibration
        never got there.
        """
        profile = self._calibrated([{"kv_mb": 1024, "max_model_len": 33000}], native=262144)
        assert self._gate(_planner(1.0), profile, available_for_kv=100_000.0) is False


class TestConfigParsing:
    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("LOGOS_MIN_CONTEXT_FRACTION", raising=False)
        assert _initial_min_context_fraction() == DEFAULT_MIN_CONTEXT_FRACTION

    def test_reads_the_env_var(self, monkeypatch):
        monkeypatch.setenv("LOGOS_MIN_CONTEXT_FRACTION", "0.75")
        assert _initial_min_context_fraction() == 0.75

    def test_garbage_falls_back_to_the_default(self, monkeypatch):
        # A typo in an operator knob must not stop the planner from planning.
        monkeypatch.setenv("LOGOS_MIN_CONTEXT_FRACTION", "half")
        assert _initial_min_context_fraction() == DEFAULT_MIN_CONTEXT_FRACTION

    def test_reads_per_model_overrides(self, monkeypatch):
        monkeypatch.setenv(
            "LOGOS_MIN_CONTEXT_FRACTION_OVERRIDES",
            '{"a/model": 1.0, "b/model": 0.25}',
        )
        assert _initial_min_context_overrides() == {"a/model": 1.0, "b/model": 0.25}

    def test_overrides_are_clamped_and_bad_entries_dropped(self, monkeypatch):
        monkeypatch.setenv(
            "LOGOS_MIN_CONTEXT_FRACTION_OVERRIDES",
            '{"a/model": 5, "b/model": -2, "c/model": "lots"}',
        )
        assert _initial_min_context_overrides() == {"a/model": 1.0, "b/model": 0.0}

    @pytest.mark.parametrize("value", ["not json", "[1, 2]", ""])
    def test_malformed_overrides_are_ignored(self, monkeypatch, value):
        monkeypatch.setenv("LOGOS_MIN_CONTEXT_FRACTION_OVERRIDES", value)
        assert _initial_min_context_overrides() == {}

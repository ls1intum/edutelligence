"""The context floor a lane has to clear to be worth placing.

Without a floor the planner takes whatever window fits the free KV cache, so
the same model ends up serving its full context on a roomy node and a fraction
of that on a busy one. Since the API can only promise the smallest window
across the cluster, the narrow lane is what every client is told the model can
do. See ``_min_context_tokens`` / ``_passes_minimum_load_feasibility``.
"""

from __future__ import annotations

from types import SimpleNamespace

from logos.capacity.capacity_planner import CapacityPlanner
from logos.sdi.models import ModelProfile


def _planner() -> CapacityPlanner:
    return CapacityPlanner.__new__(CapacityPlanner)


def _profile(
    *,
    native: int | None = None,
    pairs: list[dict] | None = None,
    fraction: float | None = None,
    name: str = "qwen/qwen3.8-27b",
) -> ModelProfile:
    return ModelProfile(
        model_name=name,
        engine="vllm",
        max_context_length=native,
        kv_cache_to_max_model_len_pairs=pairs,
        min_context_fraction=fraction,
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
        assert _planner()._min_context_tokens(_profile(native=262144, fraction=0.5)) == 131072

    def test_no_fraction_means_no_floor(self):
        """A worker that sets nothing places the model at any width.

        That is the behaviour from before the field existed, so a worker whose
        config was never touched keeps working exactly as it did.
        """
        assert _planner()._min_context_tokens(_profile(native=262144)) == 0
        assert _planner()._min_context_tokens(_profile(native=262144, fraction=0.0)) == 0

    def test_full_context_or_nothing(self):
        assert _planner()._min_context_tokens(_profile(native=262144, fraction=1.0)) == 262144

    def test_fraction_is_clamped(self):
        assert _planner()._min_context_tokens(_profile(native=100000, fraction=5.0)) == 100000
        assert _planner()._min_context_tokens(_profile(native=100000, fraction=-1.0)) == 0

    def test_unknown_context_length_is_never_blocked(self):
        """The floor stops the planner choosing narrow, not uncalibrated loads.

        A model whose context length nobody reported has no share to take, so
        gating on it would keep the model off the cluster entirely.
        """
        assert _planner()._min_context_tokens(_profile(fraction=1.0)) == 0


class TestFeasibilityGate:
    """``_passes_minimum_load_feasibility`` with the floor applied."""

    def _gate(self, profile, available_for_kv: float | None):
        planner = _planner()
        # Stub out the VRAM arithmetic: this test is about the context floor,
        # and the memory path has its own tests.
        planner._estimate_model_loaded_vram = lambda p: 1000.0
        planner._estimate_available_for_kv_mb = lambda p, c, pid, tp: available_for_kv
        planner._check_per_gpu_feasibility = lambda *a, **kw: True
        planner.get_pending_vram_mb = lambda pid: 0.0
        capacity = SimpleNamespace(available_vram_mb=80_000.0)
        return planner._passes_minimum_load_feasibility(profile.model_name, profile, capacity, provider_id=1)

    def _calibrated(self, pairs: list[dict], native: int, fraction: float | None) -> ModelProfile:
        profile = _profile(native=native, pairs=pairs, fraction=fraction)
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
            fraction=0.5,
        )
        assert self._gate(profile, available_for_kv=2000.0) is False

    def test_places_when_a_wide_enough_point_fits(self):
        profile = self._calibrated(
            [{"kv_mb": 1024, "max_model_len": 33000}, {"kv_mb": 8192, "max_model_len": 262144}],
            native=262144,
            fraction=0.5,
        )
        assert self._gate(profile, available_for_kv=9000.0) is True

    def test_no_floor_keeps_the_old_behaviour(self):
        profile = self._calibrated(
            [{"kv_mb": 1024, "max_model_len": 33000}, {"kv_mb": 8192, "max_model_len": 262144}],
            native=262144,
            fraction=None,
        )
        assert self._gate(profile, available_for_kv=2000.0) is True

    def test_refuses_when_no_point_can_ever_reach_the_floor(self):
        """Nothing freeing up will help, so say so instead of retrying forever.

        This is the "full context or nothing" case on a node whose calibration
        never got there.
        """
        profile = self._calibrated([{"kv_mb": 1024, "max_model_len": 33000}], native=262144, fraction=1.0)
        assert self._gate(profile, available_for_kv=100_000.0) is False


class TestPairSelectionRespectsTheFloor:
    """The floor also constrains which pair a load actually picks.

    The feasibility gate only screens planner-initiated loads. Contention and
    request-time cold loads reach ``_build_load_params`` directly, so the choice
    itself has to know about the floor or those paths would quietly place a
    below-floor lane.
    """

    PAIRS = [
        {"kv_mb": 1024, "max_model_len": 33000, "parallelity": 4},
        {"kv_mb": 8192, "max_model_len": 262144, "parallelity": 2},
    ]

    def test_below_floor_pairs_are_not_selectable(self):
        profile = _profile(native=262144, pairs=self.PAIRS, fraction=0.5)
        # Only the 1024 MB point fits, and it serves less than half the context.
        kv_mb, mml = CapacityPlanner._select_kv_mb_max_model_len_pair(
            profile, available_for_kv_mb=2000.0, min_context_tokens=131072
        )
        assert (kv_mb, mml) == (None, None)

    def test_wide_enough_pair_is_selected_normally(self):
        profile = _profile(native=262144, pairs=self.PAIRS, fraction=0.5)
        kv_mb, mml = CapacityPlanner._select_kv_mb_max_model_len_pair(
            profile, available_for_kv_mb=9000.0, min_context_tokens=131072
        )
        assert (kv_mb, mml) == (8192.0, 262144)

    def test_no_floor_selects_as_before(self):
        profile = _profile(native=262144, pairs=self.PAIRS)
        kv_mb, mml = CapacityPlanner._select_kv_mb_max_model_len_pair(profile, available_for_kv_mb=2000.0)
        assert (kv_mb, mml) == (1024.0, 33000)

    def test_request_time_load_places_the_widest_that_fits(self):
        """A waiting request still gets served, at the widest window available.

        The floor means "prefer not to place", not "never place" — but when a
        load happens anyway it must take the widest fitting pair, not the
        narrowest, since context is precisely what the floor is protecting.
        """
        planner = _planner()
        planner._estimate_available_for_kv_mb = lambda p, c, pid, tp: 4000.0
        planner._infer_tensor_parallel = lambda p, c, pid: None
        planner._model_defaults_to_thinking = staticmethod(lambda name: False)
        profile = _profile(
            native=262144,
            pairs=[
                {"kv_mb": 1024, "max_model_len": 33000, "parallelity": 4},
                {"kv_mb": 2048, "max_model_len": 66000, "parallelity": 3},
                {"kv_mb": 8192, "max_model_len": 262144, "parallelity": 2},
            ],
            fraction=1.0,
        )
        params = planner._build_load_params("qwen/qwen3.8-27b", "lane-1", profile, capacity=None, provider_id=1)
        # 8192 does not fit in 4000; 2048 is the widest that does.
        assert params["vllm_config"]["max_model_len"] == 66000


class TestNativeContextLengthEdgeCases:
    def test_zero_when_nothing_is_known(self):
        assert CapacityPlanner._native_context_length(_profile()) == 0
        assert CapacityPlanner._native_context_length(None) == 0

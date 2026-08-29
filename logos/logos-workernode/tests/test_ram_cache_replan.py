"""Tests for the periodic host-RAM-aware RAM cache re-plan (main.py).

The startup plan is a snapshot: after boot, the orchestrator puts lanes to
sleep (weights → host RAM) and stops them (RAM free), and the cache has to
follow. These tests cover the pieces the loop is built from:

  * ``_build_ram_cache_candidates`` — the same candidate arithmetic as at
    startup, factored out so both places agree.
  * ``_apply_ram_cache_plan`` — floor refresh + reclaim, with the protection
    of models a live lane still reads.
  * ``_lane_models_with_live_processes`` — what "live lane" means here.
  * ``_replan_ram_cache_once`` — end to end against fake app state.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import logos_worker_node.main as worker_main
from logos_worker_node.models import AppConfig, HostMemorySummary, LogosConfig, ProcessState


def _mb(mb: float) -> int:
    return int(mb * 1024 * 1024)


class _FakeProfile:
    def __init__(self, base_residency_mb: float, sleeping_mb: float | None = None) -> None:
        self.base_residency_mb = base_residency_mb
        self._sleeping_mb = sleeping_mb if sleeping_mb is not None else base_residency_mb

    def estimate_sleeping_host_ram_mb(self) -> float:
        return self._sleeping_mb


class _FakeRegistry:
    def __init__(self, profiles: dict[str, _FakeProfile | None]) -> None:
        self._profiles = profiles

    def get_profile(self, name: str):
        return self._profiles.get(name)


class _FakeCache:
    """Just enough of ModelRamCache for the re-plan to operate on."""

    def __init__(self, cached: list[str] | None = None, sizes: dict[str, int] | None = None) -> None:
        self.enabled = True
        self._cached = set(cached or [])
        self._sizes = sizes or {}
        self.floor_mb = 0.0
        self.floor_calls = 0
        self.reclaimed: list[list[str]] = []
        self.recache_calls: list[list[str]] = []

    def model_size_bytes(self, name: str) -> int:
        return self._sizes.get(name, 0)

    def held_bytes(self) -> int:
        return sum(self._sizes.get(m, 0) for m in self._cached)

    def set_host_ram_floor_mb(self, floor_mb: float) -> None:
        self.floor_mb = floor_mb
        self.floor_calls += 1

    def reclaim(self, keep: set[str]) -> list[str]:
        removed = sorted(self._cached - keep)
        self._cached -= set(removed)
        self.reclaimed.append(removed)
        return removed

    def is_cached(self, name: str) -> bool:
        return name in self._cached

    def start_background_caching(self, models: list[str]) -> None:
        self.recache_calls.append(list(models))


class _FakeHandle:
    def __init__(self, lane_id: str, model: str, state: ProcessState) -> None:
        self.lane_id = lane_id
        self.lane_config = SimpleNamespace(model=model)
        self._state = state

    def status(self):
        return SimpleNamespace(state=self._state)


class _FakeLaneManager:
    def __init__(self, handles: dict[str, _FakeHandle]) -> None:
        self._handles = handles

    def lane_ids(self) -> list[str]:
        return list(self._handles)

    def get_handle(self, lane_id: str):
        return self._handles.get(lane_id)


def _host_memory(available_mb: float) -> HostMemorySummary:
    return HostMemorySummary(
        timestamp=datetime.now(timezone.utc),
        source="proc-meminfo",
        total_mb=512000.0,
        available_mb=available_mb,
        used_mb=512000.0 - available_mb,
    )


def _app(
    cache: _FakeCache, registry: _FakeRegistry, lane_manager: _FakeLaneManager, caps: list[str]
) -> SimpleNamespace:
    cfg = AppConfig(logos=LogosConfig(capabilities_models=caps))
    return SimpleNamespace(
        state=SimpleNamespace(
            config=cfg,
            model_cache=cache,
            model_profiles=registry,
            lane_manager=lane_manager,
        )
    )


# ── _build_ram_cache_candidates ──────────────────────────────────────────────


def test_build_candidates_skips_uncalibrated_models() -> None:
    registry = _FakeRegistry(
        {
            "org/sleepable": _FakeProfile(base_residency_mb=20_000.0, sleeping_mb=18_000.0),
            "org/uncalibrated": None,
            "org/zero-residency": _FakeProfile(base_residency_mb=0.0),
        }
    )
    cache = _FakeCache(sizes={"org/sleepable": _mb(10_000)})
    cfg = AppConfig(logos=LogosConfig(capabilities_models=["org/sleepable", "org/uncalibrated", "org/zero-residency"]))

    candidates, uncalibrated = worker_main._build_ram_cache_candidates(
        cfg, cache, registry, list(cfg.logos.capabilities_models)
    )

    assert uncalibrated == ["org/uncalibrated", "org/zero-residency"]
    assert [c.name for c in candidates] == ["org/sleepable"]
    # The reserve is sized by the *sleeping* residency, not the awake one.
    assert candidates[0].sleeping_host_ram_mb == 18_000.0
    assert candidates[0].can_sleep is True
    assert candidates[0].size_bytes == _mb(10_000)


def test_build_candidates_falls_back_to_disk_size_for_unknown_sleeping_ram() -> None:
    registry = _FakeRegistry({"org/m": _FakeProfile(base_residency_mb=20_000.0, sleeping_mb=0.0)})
    cache = _FakeCache(sizes={"org/m": _mb(7_500)})
    cfg = AppConfig(logos=LogosConfig(capabilities_models=["org/m"]))

    candidates, _ = worker_main._build_ram_cache_candidates(cfg, cache, registry, ["org/m"])

    assert candidates[0].sleeping_host_ram_mb == 7_500.0


def test_build_candidates_honors_the_sleep_mode_kill_switch() -> None:
    registry = _FakeRegistry({"org/m": _FakeProfile(base_residency_mb=20_000.0)})
    cache = _FakeCache(sizes={"org/m": _mb(7_500)})
    cfg = AppConfig(logos=LogosConfig(capabilities_models=["org/m"]))
    cfg.engines.vllm.disable_sleep_mode = True

    candidates, _ = worker_main._build_ram_cache_candidates(cfg, cache, registry, ["org/m"])

    assert candidates[0].can_sleep is False


# ── _apply_ram_cache_plan ────────────────────────────────────────────────────


def test_apply_plan_sets_floor_and_reclaims_outside_the_plan() -> None:
    from logos_worker_node.cache_planner import CachePlan

    plan = CachePlan(
        order=["small"],
        reserved_for_sleep_mb=60_000.0,
        available_host_ram_mb=100_000.0,
        cache_held_mb=48_000.0,
        safety_margin_mb=8_192.0,
        sleepable_tmpfs_budget_mb=40_000.0,
        cached_unsleepable=[],
        cached_sleepable=["small"],
        skipped_sleepable=["big"],
    )
    cache = _FakeCache(cached=["small", "big"])

    removed = worker_main._apply_ram_cache_plan(cache, plan, protected=set())

    assert removed == ["big"]
    assert cache.floor_mb == pytest.approx(60_000.0 + 8_192.0)


def test_apply_plan_spares_protected_models_even_when_the_plan_skipped_them() -> None:
    from logos_worker_node.cache_planner import CachePlan

    plan = CachePlan(
        order=["small"],
        reserved_for_sleep_mb=60_000.0,
        available_host_ram_mb=100_000.0,
        cache_held_mb=48_000.0,
        safety_margin_mb=8_192.0,
        sleepable_tmpfs_budget_mb=40_000.0,
        cached_unsleepable=[],
        cached_sleepable=["small"],
        skipped_sleepable=["big"],
    )
    cache = _FakeCache(cached=["small", "big"])

    # "big" is outside the plan, but a live lane still reads it — evicting it
    # would turn the next wake into a failed lane.
    removed = worker_main._apply_ram_cache_plan(cache, plan, protected={"big"})

    assert removed == []
    assert cache.is_cached("big") is True


# ── _lane_models_with_live_processes ─────────────────────────────────────────


def test_live_processes_cover_running_and_starting_lanes_only() -> None:
    lanes = _FakeLaneManager(
        {
            "a": _FakeHandle("a", "org/a", ProcessState.RUNNING),
            "b": _FakeHandle("b", "org/b", ProcessState.STARTING),
            "c": _FakeHandle("c", "org/c", ProcessState.STOPPED),
            "d": _FakeHandle("d", "org/d", ProcessState.ERROR),
            "e": _FakeHandle("e", "org/e", ProcessState.NOT_STARTED),
        }
    )

    assert worker_main._lane_models_with_live_processes(lanes) == {"org/a", "org/b"}


# ── _replan_ram_cache_once ───────────────────────────────────────────────────


def test_replan_reclaims_when_host_ram_becomes_tight(monkeypatch) -> None:
    """Both models were cached at boot with plenty of RAM. A lane has since
    slept (weights now in host RAM) and MemAvailable dropped — the plan no
    longer fits the big model, so the cache gives its share back."""
    monkeypatch.setattr(worker_main, "_build_host_memory_summary", lambda: _host_memory(60_000.0))

    registry = _FakeRegistry(
        {
            "org/small": _FakeProfile(base_residency_mb=10_000.0, sleeping_mb=10_000.0),
            "org/big": _FakeProfile(base_residency_mb=50_000.0, sleeping_mb=50_000.0),
        }
    )
    sizes = {"org/small": _mb(8_000), "org/big": _mb(48_000)}
    cache = _FakeCache(cached=["org/small", "org/big"], sizes=sizes)
    lanes = _FakeLaneManager({})
    app = _app(cache, registry, lanes, ["org/small", "org/big"])

    asyncio.run(worker_main._replan_ram_cache_once(app))

    assert cache.reclaimed[-1] == ["org/big"]
    # The floor moved to the live reserve + margin, bounding every later copy.
    assert cache.floor_mb == pytest.approx(60_000.0 + worker_main.HOST_RAM_SAFETY_MARGIN_MB)
    # Nothing re-queued: the plan still covers what the cache holds.
    assert cache.recache_calls == []


def test_replan_recaches_when_ram_frees_up(monkeypatch) -> None:
    """The previous tick evicted the big model. Lanes have since stopped, the
    plan admits it again, and the cache should grow back in the background."""
    monkeypatch.setattr(worker_main, "_build_host_memory_summary", lambda: _host_memory(300_000.0))

    registry = _FakeRegistry(
        {
            "org/small": _FakeProfile(base_residency_mb=10_000.0, sleeping_mb=10_000.0),
            "org/big": _FakeProfile(base_residency_mb=50_000.0, sleeping_mb=50_000.0),
        }
    )
    sizes = {"org/small": _mb(8_000), "org/big": _mb(48_000)}
    cache = _FakeCache(cached=["org/small"], sizes=sizes)
    lanes = _FakeLaneManager({})
    app = _app(cache, registry, lanes, ["org/small", "org/big"])

    asyncio.run(worker_main._replan_ram_cache_once(app))

    assert cache.reclaimed[-1] == []
    assert cache.recache_calls == [["org/big"]]


def test_replan_never_evicts_a_model_a_live_lane_reads(monkeypatch) -> None:
    monkeypatch.setattr(worker_main, "_build_host_memory_summary", lambda: _host_memory(60_000.0))

    registry = _FakeRegistry(
        {
            "org/small": _FakeProfile(base_residency_mb=10_000.0, sleeping_mb=10_000.0),
            "org/big": _FakeProfile(base_residency_mb=50_000.0, sleeping_mb=50_000.0),
        }
    )
    sizes = {"org/small": _mb(8_000), "org/big": _mb(48_000)}
    cache = _FakeCache(cached=["org/small", "org/big"], sizes=sizes)
    # The big model's lane is awake and serving — its weights directory must
    # survive even though the plan skipped the model.
    lanes = _FakeLaneManager({"big": _FakeHandle("big", "org/big", ProcessState.RUNNING)})
    app = _app(cache, registry, lanes, ["org/small", "org/big"])

    asyncio.run(worker_main._replan_ram_cache_once(app))

    assert cache.reclaimed[-1] == []
    assert cache.is_cached("org/big") is True


def test_replan_is_a_noop_when_the_cache_is_disabled(monkeypatch) -> None:
    monkeypatch.setattr(worker_main, "_build_host_memory_summary", lambda: _host_memory(60_000.0))

    cache = _FakeCache()
    cache.enabled = False
    registry = _FakeRegistry({"org/small": _FakeProfile(base_residency_mb=10_000.0)})
    app = _app(cache, registry, _FakeLaneManager({}), ["org/small"])

    asyncio.run(worker_main._replan_ram_cache_once(app))

    assert cache.floor_calls == 0
    assert cache.reclaimed == []
    assert cache.recache_calls == []


def test_replan_loop_survives_a_failed_tick(monkeypatch) -> None:
    """A tick that raises (a /proc read hiccup, a profile registry error) must
    not kill the loop — the next tick re-runs the same arithmetic."""
    calls = {"n": 0}

    async def _flaky(_app):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated tick failure")

    real_sleep = worker_main.asyncio.sleep
    sleeps = {"n": 0}

    async def _counting_sleep(_s):  # noqa: ANN001
        # Yield to the event loop like the real sleep does, but end the task
        # after the third tick so the test runs a bounded number of loops.
        sleeps["n"] += 1
        if sleeps["n"] == 3:
            raise worker_main.asyncio.CancelledError()
        await real_sleep(0)

    monkeypatch.setattr(worker_main, "_replan_ram_cache_once", _flaky)
    monkeypatch.setattr(worker_main.asyncio, "sleep", _counting_sleep)

    async def _run() -> None:
        task = worker_main.asyncio.create_task(worker_main._ram_cache_replan_loop(SimpleNamespace()))
        try:
            await task
        except worker_main.asyncio.CancelledError:
            pass

    asyncio.run(_run())
    # Tick 1 raised and was swallowed, tick 2 ran, tick 3 ended the task.
    assert calls["n"] == 2

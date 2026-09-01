"""Tests for the periodic host-RAM-aware RAM cache re-plan (main.py).

The startup plan is a snapshot: after boot, the orchestrator puts lanes to
sleep (weights → host RAM) and stops them (RAM free), and the cache has to
follow. These tests cover the pieces the loop is built from:

  * ``_build_ram_cache_candidates`` — the same candidate arithmetic as at
    startup, factored out so both places agree.
  * ``_apply_ram_cache_plan`` — floor refresh + reclaim, with the protection
    of models a live lane still reads (including the corner where that
    protection blocks every eviction).
  * ``_lane_models_with_live_processes`` — what "live lane" means here.
  * ``_host_ram_safety_margin_mb`` — the host-size-scaled safety margin.
  * ``_replan_ram_cache_once`` — end to end against fake app state: skipping
    a bad /proc/meminfo read, not double-reserving an already-asleep model,
    the re-cache hold-down, and a failed tick being an operational event.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
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
    """Just enough of ModelRamCache for the re-plan to operate on.

    ``caching_now`` / ``queue`` mirror the background worker's state so the
    reclaim coordination (skip in-flight copies, purge rejected queue
    entries) is exercised the same way the real cache does it.
    """

    def __init__(
        self,
        cached: list[str] | None = None,
        sizes: dict[str, int] | None = None,
        queue: list[str] | None = None,
        caching_now: str | None = None,
    ) -> None:
        self.enabled = True
        self._cached = set(cached or [])
        self._sizes = sizes or {}
        self.queue = list(queue or [])
        self.caching_now = caching_now
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

    async def reclaim(self, keep: set[str]) -> list[str]:
        # Same coordination as ModelRamCache.reclaim: a copy in flight is
        # left alone, rejected queue entries are dropped.
        removed = sorted(m for m in self._cached - keep if m != self.caching_now)
        self._cached -= set(removed)
        self.queue = [m for m in self.queue if m in keep]
        self.reclaimed.append(removed)
        return removed

    def cached_models(self) -> list[str]:
        return sorted(self._cached)

    def pending_or_caching(self) -> set[str]:
        pending = set(self.queue)
        if self.caching_now is not None:
            pending.add(self.caching_now)
        return pending

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
    def __init__(
        self,
        handles: dict[str, _FakeHandle],
        sleeping: set[str] | None = None,
        starting: set[str] | None = None,
    ) -> None:
        self._handles = handles
        self.sleeping = set(sleeping or set())
        self._starting = set(starting or set())

    @property
    def lane_ids(self) -> list[str]:
        # Matches the real LaneManager: a list-valued property, NOT a method.
        # Defining it as a method here used to mask a ``lane_ids()`` call in
        # the re-plan path (see test_replan_reaches_plan_when_lane_ids_is_property).
        return list(self._handles)

    def get_handle(self, lane_id: str):
        return self._handles.get(lane_id)

    async def sleeping_models(self) -> set[str]:
        return set(self.sleeping)

    def starting_models(self) -> frozenset[str]:
        return frozenset(self._starting)


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
            ram_cache_replan_lock=asyncio.Lock(),
            ram_cache_in_plan_ticks={},
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

    removed = asyncio.run(worker_main._apply_ram_cache_plan(cache, plan, protected=set()))

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
    removed = asyncio.run(worker_main._apply_ram_cache_plan(cache, plan, protected={"big"}))

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


def test_live_processes_include_models_in_lane_startup() -> None:
    """A model whose lane is mid-spawn has no registered handle yet, but its
    startup reservation must still protect it — and once the reservation is
    released (handle registered, or failed startup cleaned up), a model with
    no live process is unprotected again."""
    lanes = _FakeLaneManager(
        {"a": _FakeHandle("a", "org/a", ProcessState.RUNNING)},
        starting={"org/b"},
    )

    assert worker_main._lane_models_with_live_processes(lanes) == {"org/a", "org/b"}

    lanes._starting.discard("org/b")  # noqa: SLF001
    assert worker_main._lane_models_with_live_processes(lanes) == {"org/a"}


def test_replan_reaches_plan_when_lane_ids_is_property(monkeypatch) -> None:
    """Regression: ``LaneManager.lane_ids`` is a ``@property`` returning a
    list, not a callable. The re-plan reads it through
    ``_lane_models_with_live_processes``; reading it as a call
    (``lane_manager.lane_ids()``) raises ``TypeError: 'list' object is not
    callable`` and aborts the tick before ``_apply_ram_cache_plan`` — so the
    live cache is never reclaimed or re-cached. This drives the single entry
    point (shared by the periodic tick and the post-sleep reactor) against a
    lane manager shaped exactly like the real one and asserts the plan was
    applied.

    ``lane_ids`` is asserted to be a property up front so a future edit cannot
    silently turn the fake back into a method and re-mask the mismatch.
    """
    assert isinstance(inspect.getattr_static(_FakeLaneManager, "lane_ids"), property)

    monkeypatch.setattr(worker_main, "_build_host_memory_summary", lambda: _host_memory(60_000.0))
    registry = _FakeRegistry(
        {
            "org/small": _FakeProfile(base_residency_mb=10_000.0, sleeping_mb=10_000.0),
            "org/big": _FakeProfile(base_residency_mb=50_000.0, sleeping_mb=50_000.0),
        }
    )
    sizes = {"org/small": _mb(8_000), "org/big": _mb(48_000)}
    cache = _FakeCache(cached=["org/small", "org/big"], sizes=sizes)
    # A live lane, so _lane_models_with_live_processes iterates lane_ids over a
    # non-empty set — exactly the line that raised before the fix.
    lanes = _FakeLaneManager({"big": _FakeHandle("big", "org/big", ProcessState.RUNNING)})
    app = _app(cache, registry, lanes, ["org/small", "org/big"])

    # Tight host RAM: the plan skips big, but big's live lane protects it. The
    # decisive assertion is that the tick reached _apply_ram_cache_plan — which
    # is what sets the host-RAM floor. A TypeError before it would leave
    # floor_calls at 0 and the cache untouched.
    asyncio.run(worker_main._replan_ram_cache_once(app))

    assert cache.floor_calls == 1  # _apply_ram_cache_plan ran — no TypeError
    assert cache.is_cached("org/big") is True  # the live-lane protection held


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
    # The floor moved to the live reserve + margin (scaled with this fake
    # host's 512 GB total), bounding every later copy.
    assert cache.floor_mb == pytest.approx(60_000.0 + worker_main._host_ram_safety_margin_mb(512_000.0))
    # Nothing re-queued: the plan still covers what the cache holds.
    assert cache.recache_calls == []


def test_replan_recaches_when_ram_frees_up(monkeypatch) -> None:
    """The previous tick evicted the big model. Lanes have since stopped, the
    plan admits it again, and the cache should grow back in the background —
    once it has been admitted for the hold-down number of consecutive ticks
    (seeded here, since this test is about the re-cache, not the hold-down)."""
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
    app.state.ram_cache_in_plan_ticks["org/big"] = worker_main.RAM_CACHE_RECACHE_HOLD_TICKS

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


def test_replan_does_not_evict_a_model_whose_lane_is_starting(monkeypatch) -> None:
    """The big model's lane is mid-startup: its spawn is reading weights from
    the tmpfs cache directory, but the handle is only registered once the
    spawn succeeds. With tight host RAM the plan skips the model, so without
    the startup reservation this very re-plan would rmtree the directory out
    from under the running spawn."""
    monkeypatch.setattr(worker_main, "_build_host_memory_summary", lambda: _host_memory(60_000.0))

    registry = _FakeRegistry(
        {
            "org/small": _FakeProfile(base_residency_mb=10_000.0, sleeping_mb=10_000.0),
            "org/big": _FakeProfile(base_residency_mb=50_000.0, sleeping_mb=50_000.0),
        }
    )
    sizes = {"org/small": _mb(8_000), "org/big": _mb(48_000)}
    cache = _FakeCache(cached=["org/small", "org/big"], sizes=sizes)
    # No handles at all — the only protection org/big has is the startup
    # reservation held by its in-flight lane add.
    lanes = _FakeLaneManager({}, starting={"org/big"})
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


# ── bad /proc/meminfo input ──────────────────────────────────────────────────


def test_replan_skips_when_meminfo_is_unavailable(monkeypatch) -> None:
    """A failed /proc/meminfo read returns source='unavailable' and
    available_mb=0. Feeding that zero into the plan would come out deeply
    negative and reclaim the whole cache. The tick must skip and leave the
    previous pass's state in place instead."""
    monkeypatch.setattr(
        worker_main,
        "_build_host_memory_summary",
        lambda: HostMemorySummary(timestamp=datetime.now(timezone.utc), source="unavailable"),
    )
    registry = _FakeRegistry({"org/small": _FakeProfile(base_residency_mb=10_000.0)})
    sizes = {"org/small": _mb(8_000)}
    cache = _FakeCache(cached=["org/small"], sizes=sizes)
    app = _app(cache, registry, _FakeLaneManager({}), ["org/small"])

    asyncio.run(worker_main._replan_ram_cache_once(app))

    # Nothing planned, no floor change, nothing evicted or re-queued.
    assert cache.floor_calls == 0
    assert cache.reclaimed == []
    assert cache.recache_calls == []
    assert cache.is_cached("org/small") is True


def test_replan_skips_when_available_mb_is_zero(monkeypatch) -> None:
    """Even with a readable /proc/meminfo, a zero MemAvailable is not a
    usable measurement — same skip, same reason."""
    monkeypatch.setattr(worker_main, "_build_host_memory_summary", lambda: _host_memory(0.0))
    registry = _FakeRegistry({"org/small": _FakeProfile(base_residency_mb=10_000.0)})
    sizes = {"org/small": _mb(8_000)}
    cache = _FakeCache(cached=["org/small"], sizes=sizes)
    app = _app(cache, registry, _FakeLaneManager({}), ["org/small"])

    asyncio.run(worker_main._replan_ram_cache_once(app))

    assert cache.floor_calls == 0
    assert cache.reclaimed == []
    assert cache.is_cached("org/small") is True


# ── no double-counting an already-asleep model ───────────────────────────────


def test_replan_does_not_double_count_an_asleep_model(monkeypatch) -> None:
    """MemAvailable has already dropped by the size of a lane that is asleep
    (its weights are in host RAM now). Reserving that model's sleeping
    footprint again would shrink the budget by the size of the sleeping
    model and over-evict — precisely the situation this loop exists to
    handle. Only models that are NOT yet asleep are reserved.

    The numbers are chosen so the two variants come out differently: with
    the fix the reserve is small's 10 GB and the budget is 120.4 GB — both
    models fit. Without it the reserve is 110 GB and the budget is 20.4 GB,
    below big's 48 GB, so big would be reclaimed."""
    # Host: 512 GB total. The big model (100 GB asleep) has since slept, so
    # MemAvailable reflects it. Both models are sleepable; only big is asleep.
    monkeypatch.setattr(worker_main, "_build_host_memory_summary", lambda: _host_memory(100_000.0))

    registry = _FakeRegistry(
        {
            "org/small": _FakeProfile(base_residency_mb=10_000.0, sleeping_mb=10_000.0),
            "org/big": _FakeProfile(base_residency_mb=100_000.0, sleeping_mb=100_000.0),
        }
    )
    sizes = {"org/small": _mb(8_000), "org/big": _mb(48_000)}
    cache = _FakeCache(cached=["org/small", "org/big"], sizes=sizes)
    # org/big is asleep — its 100 GB sleeping footprint is already
    # subtracted from the MemAvailable reading.
    lanes = _FakeLaneManager({}, sleeping={"org/big"})
    app = _app(cache, registry, lanes, ["org/small", "org/big"])

    asyncio.run(worker_main._replan_ram_cache_once(app))

    # Reserve must cover only org/small (10 GB), not org/big (100 GB): big is
    # already asleep and already counted in MemAvailable. If big were
    # double-reserved the budget would drop below big's size and the plan
    # would reclaim it. The floor is reserved + margin, so it too must
    # reflect only the still-awake reserve.
    assert cache.reclaimed[-1] == []
    assert cache.floor_mb == pytest.approx(10_000.0 + worker_main._host_ram_safety_margin_mb(512_000.0))


def test_replan_keeps_an_asleep_model_its_lane_still_reads(monkeypatch) -> None:
    """The double-count fix must not become an under-reserve: an asleep model
    is excluded from the reserve, but a *different* sleepable model that is
    still awake is fully reserved, and the asleep model still gets its live
    lane's protection. Here big is asleep AND its lane is live (protected);
    small is awake and reserved in full."""
    monkeypatch.setattr(worker_main, "_build_host_memory_summary", lambda: _host_memory(300_000.0))

    registry = _FakeRegistry(
        {
            "org/small": _FakeProfile(base_residency_mb=10_000.0, sleeping_mb=10_000.0),
            "org/big": _FakeProfile(base_residency_mb=100_000.0, sleeping_mb=100_000.0),
        }
    )
    sizes = {"org/small": _mb(8_000), "org/big": _mb(48_000)}
    cache = _FakeCache(cached=["org/small", "org/big"], sizes=sizes)
    # big is asleep AND its lane is live (protected). small is awake.
    lanes = _FakeLaneManager(
        {"big": _FakeHandle("big", "org/big", ProcessState.RUNNING)},
        sleeping={"org/big"},
    )
    app = _app(cache, registry, lanes, ["org/small", "org/big"])

    asyncio.run(worker_main._replan_ram_cache_once(app))

    # small (awake) is reserved in full; big (asleep) is not reserved again
    # but is protected from eviction. So the floor covers small's 10 GB plus
    # the margin, and big survives despite the plan's arithmetic.
    assert cache.reclaimed[-1] == []
    assert cache.is_cached("org/big") is True
    assert cache.floor_mb == pytest.approx(10_000.0 + worker_main._host_ram_safety_margin_mb(512_000.0))


# ── protected blocks every eviction ──────────────────────────────────────────


def test_replan_logs_warning_when_every_eviction_is_protected(monkeypatch, caplog) -> None:
    """Corner: the plan no longer covers a cached model, but that model is
    read by a live lane, so it is protected and the re-plan frees nothing.
    That is a pressure state the cache cannot relieve — it must be logged as
    a warning, not stay silent."""
    monkeypatch.setattr(worker_main, "_build_host_memory_summary", lambda: _host_memory(60_000.0))

    registry = _FakeRegistry(
        {
            "org/small": _FakeProfile(base_residency_mb=10_000.0, sleeping_mb=10_000.0),
            "org/big": _FakeProfile(base_residency_mb=50_000.0, sleeping_mb=50_000.0),
        }
    )
    sizes = {"org/small": _mb(8_000), "org/big": _mb(48_000)}
    cache = _FakeCache(cached=["org/small", "org/big"], sizes=sizes)
    # The plan will skip big (tight RAM), but big's lane is live → protected.
    lanes = _FakeLaneManager({"big": _FakeHandle("big", "org/big", ProcessState.RUNNING)})
    app = _app(cache, registry, lanes, ["org/small", "org/big"])

    with caplog.at_level(logging.WARNING, logger="logos_worker_node"):
        asyncio.run(worker_main._replan_ram_cache_once(app))

    # Nothing was evicted (big is protected), and the corner was surfaced.
    assert cache.reclaimed[-1] == []
    assert cache.is_cached("org/big") is True
    assert any("cannot free host RAM" in rec.getMessage() and "org/big" in rec.getMessage() for rec in caplog.records)


# ── re-cache hold-down ────────────────────────────────────────────────────────


def test_replan_recaches_only_after_hold_down_ticks(monkeypatch) -> None:
    """A model the plan newly admits is not re-queued on the very first tick.
    It must be admitted for RAM_CACHE_RECACHE_HOLD_TICKS consecutive ticks, so
    a model sitting near the budget line with jittering MemAvailable is not
    evicted on one tick and re-queued on the next while its copy takes
    minutes."""
    monkeypatch.setattr(worker_main, "_build_host_memory_summary", lambda: _host_memory(300_000.0))

    registry = _FakeRegistry(
        {
            "org/small": _FakeProfile(base_residency_mb=10_000.0, sleeping_mb=10_000.0),
            "org/big": _FakeProfile(base_residency_mb=50_000.0, sleeping_mb=50_000.0),
        }
    )
    sizes = {"org/small": _mb(8_000), "org/big": _mb(48_000)}
    # big was evicted earlier: the cache holds only small, the plan admits big.
    cache = _FakeCache(cached=["org/small"], sizes=sizes)
    lanes = _FakeLaneManager({})
    app = _app(cache, registry, lanes, ["org/small", "org/big"])

    async def _run() -> None:
        # All ticks in ONE event loop: the re-plan lock is bound to the loop
        # that first uses it.
        # Tick 1: big is admitted for the first time — below the hold-down,
        # so it is NOT re-queued yet.
        await worker_main._replan_ram_cache_once(app)
        assert cache.recache_calls == []
        # Enough further ticks to reach the hold-down, then big is re-queued.
        for _ in range(worker_main.RAM_CACHE_RECACHE_HOLD_TICKS - 1):
            await worker_main._replan_ram_cache_once(app)

    asyncio.run(_run())
    assert cache.recache_calls == [["org/big"]]


def test_replan_does_not_requeue_a_model_the_worker_already_owns(monkeypatch) -> None:
    """While a copy is in flight (or queued), is_cached is False — so a naive
    're-cache everything the plan admits' would re-queue and re-log the same
    model every tick. The worker's own models (queued or in flight) are
    excluded from the re-cache set."""
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
    # Seed the hold-down so the only thing standing between big and a
    # re-cache is the fact that the worker already has it in flight.
    app.state.ram_cache_in_plan_ticks["org/big"] = worker_main.RAM_CACHE_RECACHE_HOLD_TICKS
    cache.caching_now = "org/big"

    asyncio.run(worker_main._replan_ram_cache_once(app))

    # big is admitted and past the hold-down, but the worker already owns it
    # — no re-queue, no log.
    assert cache.recache_calls == []


# ── host-size-scaled safety margin ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("total_mb", "expected"),
    [
        # No usable total (non-Linux / failed read) → the old absolute floor.
        (0.0, 8192.0),
        (None, 8192.0),
        # Small host: 5% is below the floor, so the floor wins.
        (64_000.0, 8192.0),
        # 64 GiB: 5% = 3200 MB < 8192 floor → floor. (12.5% old value)
        # Mid host: ratio kicks in above the floor.
        (200_000.0, 10_000.0),
        # Large host: 5% of 512 GB.
        (512_000.0, 25_600.0),
        # Very large host: capped at the max.
        (1_000_000.0, 32_768.0),
    ],
)
def test_safety_margin_scales_with_host_size(total_mb, expected) -> None:
    """A flat 8 GiB is 12.5% of a 64 GB host but 1.6% of a 512 GB one, and the
    cold-load spike the margin covers scales with model size. So the margin
    is a ratio of host RAM clamped to [floor, cap]."""
    assert worker_main._host_ram_safety_margin_mb(total_mb) == pytest.approx(expected)


def test_replan_floor_uses_host_scaled_margin(monkeypatch) -> None:
    """End to end: the floor set by a re-plan is reserve + the margin scaled
    to this host's total (512 GB fake → 5%), not a flat 8 GiB."""
    monkeypatch.setattr(worker_main, "_build_host_memory_summary", lambda: _host_memory(300_000.0))
    registry = _FakeRegistry({"org/small": _FakeProfile(base_residency_mb=10_000.0)})
    sizes = {"org/small": _mb(8_000)}
    cache = _FakeCache(cached=["org/small"], sizes=sizes)
    app = _app(cache, registry, _FakeLaneManager({}), ["org/small"])

    asyncio.run(worker_main._replan_ram_cache_once(app))

    assert cache.floor_mb == pytest.approx(10_000.0 + worker_main._host_ram_safety_margin_mb(512_000.0))
    # And that is 5% of the 512 GB host, not the flat 8 GiB.
    assert cache.floor_mb == pytest.approx(10_000.0 + 25_600.0)


# ── a failed tick is an operational event ────────────────────────────────────


def test_replan_loop_failed_tick_is_logged_as_warning(monkeypatch, caplog) -> None:
    """When a tick fails the cache is left in whatever state the last
    successful pass produced — potentially oversized under pressure. That is
    an operational event and must be visible at production log levels
    (warning), not buried at debug."""
    calls = {"n": 0}

    async def _flaky(_app):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated tick failure")

    real_sleep = worker_main.asyncio.sleep
    sleeps = {"n": 0}

    async def _counting_sleep(_s):  # noqa: ANN001
        sleeps["n"] += 1
        if sleeps["n"] == 2:
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

    with caplog.at_level(logging.WARNING, logger="logos_worker_node"):
        asyncio.run(_run())

    assert calls["n"] == 1
    assert any("re-plan failed" in rec.message.lower() and rec.levelno >= logging.WARNING for rec in caplog.records)

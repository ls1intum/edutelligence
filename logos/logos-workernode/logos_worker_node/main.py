"""FastAPI application entry point for LogosWorkerNode."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator

if TYPE_CHECKING:
    from logos_worker_node.models import AppConfig

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from logos_worker_node.cache_planner import CacheCandidate, CachePlan, plan_cache_order
from logos_worker_node.calibration import auto_calibrate_models, plans_from_config
from logos_worker_node.config import get_state_dir, load_config
from logos_worker_node.gpu import GpuMetricsCollector
from logos_worker_node.gpu_watchdog import GpuWatchdog
from logos_worker_node.lane_manager import LaneManager, _lane_id_from_config
from logos_worker_node.logos_bridge import LogosBridgeClient
from logos_worker_node.model_cache import ModelRamCache, _DisabledModelRamCache, create_model_cache
from logos_worker_node.model_profiles import ModelProfileRegistry
from logos_worker_node.models import ProcessState, model_can_sleep
from logos_worker_node.runtime import SERVICE_VERSION, _build_host_memory_summary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("logos_worker_node")

_LANE_MANAGER_SHUTDOWN_TIMEOUT = 90

# Host-RAM safety buffer the RAM cache plan must leave untouched: OS page
# cache, malloc fragmentation, vLLM mm processor caches, monitoring agents,
# and the spike during a single lane's cold load.
#
# Scaled with the host's total RAM instead of fixed: the cold-load spike grows
# with model size, and model size grows with the host that runs it — a flat
# 8 GiB is 12.5% of a 64 GiB box but 1.6% of a 512 GiB one, exactly the class
# of machine where a single cold load can overshoot it. The floor keeps hosts
# up to 164 GiB at the old absolute value; the cap keeps the ratio from
# reserving a large share of very large hosts. Shared by startup and the
# re-plan so the cache's growth bound is computed identically in both places.
_HOST_RAM_SAFETY_MARGIN_MIN_MB = 8192.0
_HOST_RAM_SAFETY_MARGIN_MAX_MB = 32768.0
_HOST_RAM_SAFETY_MARGIN_RATIO = 0.05


def _host_ram_safety_margin_mb(total_host_ram_mb: float | None) -> float:
    """The safety margin for a host with *total_host_ram_mb* of RAM.

    The ratio of the total, clamped to ``[MIN, MAX]``. An unknown total (no
    /proc/meminfo, non-Linux dev box) falls back to the floor — the old
    absolute value.
    """
    if not total_host_ram_mb or total_host_ram_mb <= 0:
        return _HOST_RAM_SAFETY_MARGIN_MIN_MB
    scaled = total_host_ram_mb * _HOST_RAM_SAFETY_MARGIN_RATIO
    return min(max(scaled, _HOST_RAM_SAFETY_MARGIN_MIN_MB), _HOST_RAM_SAFETY_MARGIN_MAX_MB)


# How often (seconds) the RAM cache plan is re-derived from the live host RAM.
# This is the backstop, not the primary reactor: a lane that sleeps re-plans
# the cache immediately (the on_lane_slept hook), so a burst of sleeps does
# not have to wait a minute for the cache to shrink. What only the tick sees:
# lanes STOPPED (their RAM frees, the cache may grow back) and drift that did
# not go through a sleep. A tick is cheap — one /proc/meminfo read plus a
# metadata walk of the source model trees.
RAM_CACHE_REPLAN_INTERVAL_S = 60.0

# A model must be admitted by the plan for this many consecutive ticks before
# the re-plan (re-)queues it for a background copy. Without it, a model
# sitting near the budget line with MemAvailable jittering is evicted on one
# tick and re-queued on the next while its multi-minute copy runs — evict/
# recopy thrash of tens of GB. Three ticks (≈3 min) rides out the jitter
# while still reusing RAM freed by stopped lanes promptly.
RAM_CACHE_RECACHE_HOLD_TICKS = 3


def _download_one_model(model_name: str, hf_home: str) -> None:
    """Blocking download of a single model into the HF hub cache.

    Uses huggingface_hub.snapshot_download with HF_TOKEN from the environment.
    Imported lazily because huggingface_hub is supplied transitively by the
    vLLM runtime image and is not a declared dependency of this package.
    """
    from huggingface_hub import snapshot_download

    # validate_capabilities checks <hf_home>/hub/models--org--name, so download
    # into <hf_home>/hub to match (HF_HUB_CACHE == HF_HOME/hub).
    cache_dir = os.path.join(hf_home, "hub")
    snapshot_download(
        repo_id=model_name,
        cache_dir=cache_dir,
        token=os.environ.get("HF_TOKEN") or None,
    )


async def _prefetch_missing_models(missing: list[str], hf_home: str) -> None:
    """Download missing capability models in the background, one at a time.

    Sequential to avoid saturating disk/network bandwidth. Each model is
    fetched in a worker thread so the event loop (heartbeats, lane commands)
    keeps running while large weights stream in. Failures are logged and do
    not abort the remaining downloads or worker startup.
    """
    logger.info("Prefetching %d missing capability model(s): %s", len(missing), missing)
    for model_name in missing:
        try:
            logger.info("Prefetch: downloading %s …", model_name)
            await asyncio.to_thread(_download_one_model, model_name, hf_home)
            logger.info("Prefetch: %s download complete", model_name)
        except Exception:
            logger.warning("Prefetch: failed to download %s", model_name, exc_info=True)


async def _auto_calibrate_if_needed(
    cfg: AppConfig,
    model_profiles: ModelProfileRegistry,
    state_dir: "Path",
    model_cache: Any | None = None,
) -> None:
    """Check for uncalibrated capabilities models and calibrate them on startup."""
    if os.getenv("LOGOS_SKIP_AUTO_CALIBRATION", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        logger.info("Auto-calibration disabled via LOGOS_SKIP_AUTO_CALIBRATION")
        return

    caps = cfg.logos.capabilities_models if cfg.logos else []
    if not caps:
        return

    # Resolve config.yml path (also needed below; resolve once and reuse).
    config_path_str = os.environ.get("LOGOS_WORKER_NODE_CONFIG", "").strip()
    if config_path_str:
        config_path = Path(config_path_str)
    else:
        for candidate in [Path("/app/config.yml"), Path("config.yml")]:
            if candidate.resolve().is_file():
                config_path = candidate
                break
        else:
            config_path = Path("config.yml")

    # Build a {model_name: (tp, enforce_eager)} table from production config.
    # A persisted profile is only valid if BOTH match what production will
    # actually run — different tp or different enforce_eager produces a
    # different VRAM footprint (CUDA graph capture pools persist across sleep
    # and add 5-15 GB to both loaded_vram_mb and sleeping_residual_mb that
    # eager-mode calibration never sees).
    #
    # tp is `None` when the operator left it unspecified — in that case the
    # calibrator's chosen tp is authoritative (it's the result of a real
    # probe) and lane_manager._auto_tensor_parallel consumes it at launch
    # time. Comparing calibrated vs default 1 would trigger an infinite
    # re-calibration loop for any model that genuinely needs tp>1.
    expected_settings: dict[str, tuple[int | None, bool]] = {}
    if config_path.exists():
        try:
            for plan in plans_from_config(config_path):
                m = plan.get("model")
                if not m:
                    continue
                explicit_tp = plan.get("tensor_parallel_size")
                expected_settings[str(m)] = (
                    int(explicit_tp) if explicit_tp is not None else None,
                    bool(plan.get("enforce_eager", False)),
                )
        except Exception as exc:
            logger.warning(
                "Could not parse plans from %s for provenance check: %s",
                config_path,
                exc,
            )

    uncalibrated = []
    for model_name in caps:
        profile = model_profiles.get_profile(model_name)
        # sleeping_residual_mb is a sleep-mode measurement: it is N/A for a model
        # that won't sleep (worker-wide kill switch, per-model
        # enable_sleep_mode=false, or the profile already flagged sleep disabled).
        # Requiring it for such a model causes an infinite re-calibration loop —
        # a nosleep lane never produces a sleep measurement, so the profile is
        # forever "incomplete" and every run re-calibrates (or, with calibration
        # skipped, the model never registers a deployment). Mirrors the
        # sleep_na handling in logos_bridge's session-driven needs_calib check.
        sleep_na = profile is not None and (bool(profile.sleep_mode_disabled) or not model_can_sleep(cfg, model_name))
        reason = None
        if profile is None:
            reason = "no profile"
        elif profile.base_residency_mb is None:
            reason = "base_residency_mb is null"
        elif (not sleep_na) and profile.sleeping_residual_mb is None:
            reason = "sleeping_residual_mb is null"
        elif (
            profile.residency_source == "calibrated"
            and profile.min_kv_cache_mb is not None
            and profile.max_kv_cache_mb is not None
            and profile.min_kv_cache_mb > 0
            and profile.min_kv_cache_mb == profile.max_kv_cache_mb
        ):
            # Collapsed KV envelope: pre-fix calibration runs read
            # ``search_lo`` after the binary search had mutated it upward to
            # equal ``best_kv``, so every recorded envelope ended up with
            # min == max. The runtime clamp needs *room* between the two
            # ends — without it the planner can't scale KV down when
            # another lane is resident. Re-calibrate to recover the floor
            # at ``_KV_CACHE_MIN_STEP_MB``. Operator-pinned profiles also
            # have min == max by design; they re-calibrate via the fast
            # explicit-kv path that skips the binary search.
            reason = (
                f"collapsed kv envelope (min={profile.min_kv_cache_mb:.0f}MB "
                f"== max={profile.max_kv_cache_mb:.0f}MB)"
            )
        elif profile.residency_source == "calibrated" and not profile.kv_cache_to_max_model_len_pairs:
            reason = "missing kv_cache_to_max_model_len_pairs"
        elif (
            profile.residency_source == "calibrated"
            and profile.loaded_vram_mb is not None
            and profile.kv_budget_mb is not None
            and profile.loaded_vram_mb - profile.base_residency_mb > 0.5 * profile.kv_budget_mb
        ):
            # Old-format calibrated profile: base_residency was stored as
            # weights-only, so loaded_vram (= weights + KV) sits roughly one
            # full kv_budget *above* base. New format stores full loaded VRAM,
            # so base ≈ loaded at calibration time and runtime EMA only nudges
            # loaded a few percent below base after real traffic (the KV pool
            # is reserved at calibration peak but rarely fully used in practice).
            #
            # Only flag as stale when `loaded - base > 0.5 × kv_budget` — that
            # captures genuine weights-only convention without firing on the
            # routine "loaded EMA-drifted below base" case, which is what every
            # restart after real traffic produces.
            #
            # "measured" profiles intentionally differ (base=weights-only,
            # loaded=weights+KV) and must NOT be flagged as stale.
            reason = f"stale format (base={profile.base_residency_mb:.0f} << loaded={profile.loaded_vram_mb:.0f}, kv_budget={profile.kv_budget_mb:.0f})"  # noqa: E501
        else:
            # Provenance check: only honor a calibrated profile if its (tp,
            # enforce_eager) matches what production will run. Mismatch means
            # the persisted numbers describe a different configuration and
            # the planner would budget VRAM incorrectly.
            expected = expected_settings.get(model_name)
            if expected is not None and profile.residency_source == "calibrated":
                expected_tp, expected_eager = expected
                cal_tp = profile.tensor_parallel_size
                cal_eager = profile.enforce_eager_at_calibration
                if expected_tp is not None and cal_tp is not None and cal_tp != expected_tp:
                    reason = f"tp mismatch (calibrated={cal_tp}, production={expected_tp})"
                elif cal_eager is not None and cal_eager != expected_eager:
                    reason = (
                        f"enforce_eager mismatch (calibrated={cal_eager}, "
                        f"production={expected_eager}) — graph footprint differs"
                    )
        if reason:
            logger.info("  %s needs calibration: %s", model_name, reason)
            uncalibrated.append(model_name)

    if not uncalibrated:
        logger.info(
            "All %d capabilities models already calibrated \u2014 skipping calibration",
            len(caps),
        )
        return

    logger.info(
        "%d of %d capabilities models need calibration: %s. Starting auto-calibration...",
        len(uncalibrated),
        len(caps),
        uncalibrated,
    )

    t0 = time.perf_counter()

    # Run synchronous calibration in a thread to avoid blocking the event loop
    nccl_p2p = cfg.engines.vllm.nccl_p2p_available if cfg.engines else False
    _mc = model_cache if (model_cache is not None and getattr(model_cache, "enabled", False)) else None
    results = await asyncio.to_thread(
        auto_calibrate_models,
        uncalibrated,
        config_path,
        state_dir,
        nccl_p2p_available=nccl_p2p,
        model_cache=_mc,
    )

    elapsed = time.perf_counter() - t0

    ok = [r for r in results.values() if r.success]
    fail = [r for r in results.values() if not r.success]

    for r in ok:
        logger.info(
            "Calibrated %s \u2014 base_residency=%.0f MB \u2014 done in calibration batch",
            r.model,
            r.base_residency_mb,
        )

    if fail:
        for r in fail:
            logger.warning(
                "Calibration failed for %s: %s (model will have no placement data)",
                r.model,
                r.error,
            )

    logger.info(
        "Auto-calibration complete (%d/%d succeeded) in %.1fs. Proceeding to normal startup.",
        len(ok),
        len(ok) + len(fail),
        elapsed,
    )

    # Reload persisted profiles into the registry so newly calibrated
    # values are available for lane placement
    if ok:
        model_profiles._load_persisted()


def _sleepable_lane_models(cfg: AppConfig, lane_manager: LaneManager | None = None) -> set[str]:
    """Configured and live lane models that can sleep.

    ``static_lanes`` may enable sleep mode for models outside
    ``capabilities_models``, and ``_add_lane_unlocked`` caches any vLLM model on
    demand (a lane added by the server, not just one from config) — so the
    re-plan reserve must cover their sleeping residency too, not just the
    capability models. Capability models are passed to
    ``_build_ram_cache_candidates`` separately; they keep the "uncalibrated ⇒
    not served" rule, but a configured/live lane model is served regardless of
    calibration, so it is reserved here even without a profile.
    """
    models: set[str] = set()
    for sl in cfg.static_lanes:
        if model_can_sleep(cfg, sl.model):
            models.add(sl.model)
    if lane_manager is not None:
        for lane_id in lane_manager.lane_ids:
            handle = lane_manager.get_handle(lane_id)
            if handle is None or handle.lane_config is None:
                continue
            if model_can_sleep(cfg, handle.lane_config.model):
                models.add(handle.lane_config.model)
    return models


def _cache_candidate(
    cfg: AppConfig,
    model_cache: ModelRamCache | _DisabledModelRamCache,
    model_profiles: ModelProfileRegistry,
    name: str,
) -> CacheCandidate:
    """A single cache-plan candidate.

    Prefers the model's calibrated/measured sleeping footprint; when that is
    unavailable (a static/live lane model outside ``capabilities_models`` is
    often uncalibrated) falls back to the on-disk size — the same conservative
    estimate used for a measured-but-never-slept capability model. A model not
    yet cached has size 0 and so reserves nothing: it holds no host RAM the
    floor must bound until it is copied.
    """
    profile = model_profiles.get_profile(name)
    sleeping_host_ram_mb = 0.0
    if profile is not None and (profile.base_residency_mb or 0) > 0:
        sleeping_host_ram_mb = profile.estimate_sleeping_host_ram_mb()
    if sleeping_host_ram_mb <= 0.0:
        # No measured/calibrated sleeping footprint. On-disk size underestimates
        # by ~tokenizer + compile cache overhead but is the right ballpark.
        sleeping_host_ram_mb = model_cache.model_size_bytes(name) / (1024 * 1024)
    return CacheCandidate(
        name=name,
        can_sleep=model_can_sleep(cfg, name),
        sleeping_host_ram_mb=sleeping_host_ram_mb,
        size_bytes=model_cache.model_size_bytes(name),
    )


def _build_ram_cache_candidates(
    cfg: AppConfig,
    model_cache: ModelRamCache | _DisabledModelRamCache,
    model_profiles: ModelProfileRegistry,
    caps: list[str],
    reserve_models: set[str] | None = None,
) -> tuple[list[CacheCandidate], list[str]]:
    """Cache-plan candidates for the capability models that have profile data.

    ``reserve_models`` are sleep-capable configured/live lane models that MUST
    enter the sleep reserve even without a profile (see
    ``_sleepable_lane_models``); they are included with the conservative
    on-disk footprint when uncalibrated instead of being skipped.

    Returns ``(candidates, uncalibrated)`` — the uncalibrated capability models
    are not served at all, so they never enter the plan (``reserve_models`` are
    the exception: they are served regardless of calibration).

    Each candidate carries the two numbers the planner balances:

      * ``sleeping_host_ram_mb`` — the RAM this model holds *while asleep*.
        The sleep reserve exists for these models being asleep at once, so the
        sleeping residency is what it has to cover. Using the awake footprint
        would double-count RAM an awake lane already holds regardless of the
        cache, and leave the actual sleep cost out of the only calculation
        that balances the two consumers of host RAM.
      * ``size_bytes`` — the tmpfs cost (the weights on disk).
    """
    reserve_models = set(reserve_models or set())
    candidates: list[CacheCandidate] = []
    uncalibrated: list[str] = []
    seen: set[str] = set()
    for m in caps:
        profile = model_profiles.get_profile(m)
        if profile is None or (profile.base_residency_mb or 0) <= 0:
            uncalibrated.append(m)
            continue
        seen.add(m)
        candidates.append(_cache_candidate(cfg, model_cache, model_profiles, m))
    for m in sorted(reserve_models - seen):
        seen.add(m)
        candidates.append(_cache_candidate(cfg, model_cache, model_profiles, m))
    return candidates, uncalibrated


async def _apply_ram_cache_plan(
    model_cache: ModelRamCache | _DisabledModelRamCache,
    plan: CachePlan,
    protected: set[str],
) -> list[str]:
    """Re-bind the cache to a plan: refresh the growth bound, evict the rest.

    ``set_host_ram_floor_mb`` bounds every later copy against the plan's sleep
    reserve (minus what is already asleep — that RAM is out of MemAvailable)
    plus safety margin, checked live against MemAvailable — so a lane that
    puts weights in host RAM shrinks the cache's room immediately, without
    anyone re-planning. ``reclaim`` drops what the plan no longer covers,
    returning that RAM to the pool. *protected* models are spared even when
    the plan skipped them: a lane that is live still reads its weights from
    the HF_HOME it was started with, and a lane waking from sleep_l2 re-reads
    them — pulling that directory out would turn a wake into a failed lane.

    The corner where *every* model the plan would evict is protected (all
    cached models currently serve a live lane) is decided in favour of the
    lanes: the protection is what keeps wakes and restarts correct, and the
    cache genuinely has no RAM to give back while its copies are in use by
    live processes. That is a pressure state the cache cannot relieve, so it
    is logged as a warning instead of staying silent — the operator's lever
    there is stopping (not just sleeping) a lane.

    Returns the names of the models that were evicted.
    """
    model_cache.set_host_ram_floor_mb(plan.reserved_for_sleep_mb + plan.safety_margin_mb)
    keep = set(plan.order) | protected
    reclaimed = await model_cache.reclaim(keep)
    if not reclaimed:
        # The plan wanted less than the cache holds, yet nothing was evicted:
        # every would-be eviction is protected by a live lane (a model the
        # plan does not want and that is not protected would have been
        # dropped). See the docstring for why the protection wins.
        spared = [m for m in model_cache.cached_models() if m not in set(plan.order)]
        if spared:
            logger.warning(
                "RAM cache cannot free host RAM right now: the plan no longer "
                "covers %d model(s), but all of them are read by live lanes "
                "(evicting would break their wakes and restarts). They are "
                "released as soon as those lanes sleep or stop: %s",
                len(spared),
                spared,
            )
    return reclaimed


def _lane_models_with_live_processes(lane_manager: LaneManager) -> set[str]:
    """Models whose lane process is (or is becoming) live.

    These are exactly the models the cache must not evict — see
    ``_apply_ram_cache_plan``. ``status()`` only checks the child process's
    return code, so this costs nothing the heartbeat does not already pay.

    Also unions the startup-transition reservations: a model whose lane is
    being spawned has no registered handle yet (the handle lands in
    ``_handles`` only once the spawn succeeds) but its spawn is already
    reading its — possibly tmpfs — model directory, so evicting it mid-
    startup would rmtree the tree out from under the process.
    """
    protected: set[str] = set()
    for lane_id in lane_manager.lane_ids:
        handle = lane_manager.get_handle(lane_id)
        if handle is None or handle.lane_config is None:
            continue
        if handle.status().state in {ProcessState.RUNNING, ProcessState.STARTING}:
            protected.add(handle.lane_config.model)
    protected |= lane_manager.starting_models()
    return protected


def _init_ram_cache_replan_state(
    app: FastAPI,
    cfg: AppConfig,
    lane_manager: LaneManager,
    model_profiles: ModelProfileRegistry,
    model_cache: ModelRamCache | _DisabledModelRamCache,
) -> None:
    """Populate the app.state fields the RAM-cache re-plan reads at call time.

    This MUST run before any startup apply_lanes call, not after it: a staggered
    sleep during apply_lanes (static lanes, then restored dynamic lanes) fires
    the on_lane_slept hook -> _replan_ram_cache_once, and _notify_lane_slept
    swallows a missing-field error — silently skipping the reclaim. Setting the
    state up here keeps the reactive hook active for the whole startup sequence.
    (gpu_collector and the bridge are wired separately, right before the bridge
    starts — nothing the re-plan reads from them.)
    """
    app.state.config = cfg
    app.state.lane_manager = lane_manager
    app.state.model_profiles = model_profiles
    app.state.model_cache = model_cache
    # Serialises the two re-plan triggers (tick + post-sleep hook) — see
    # _replan_ram_cache_once.
    app.state.ram_cache_replan_lock = asyncio.Lock()
    # model -> consecutive ticks it has been admitted by the plan; drives the
    # re-cache hold-down (see _run_ram_cache_replan).
    app.state.ram_cache_in_plan_ticks: dict[str, int] = {}


async def _replan_ram_cache_once(app: FastAPI) -> None:
    """Re-derive and apply the host-RAM-aware cache plan from live data.

    This is the single entry point for both re-plan triggers:

    * the periodic tick — the backstop, which is what sees lanes STOPPED
      (RAM frees, the cache may grow back) and any drift that did not go
      through a sleep;
    * the post-sleep hook (``LaneManager(on_lane_slept=...)``) — the
      reactive path, which runs the moment a lane's weights land in host RAM,
      so several lanes sleeping in quick succession do not face a cache that
      keeps its old size for up to a minute while the host OOM killer is the
      only other "reactor" in the room (and it picks vLLM).

    The lock serialises the two: a re-plan must not read ``held_bytes`` or
    evict while another pass is mid-reclaim (a size walk racing an ``rmtree``
    would undercount the cache and the second plan could evict models the
    first still keeps).
    """
    async with app.state.ram_cache_replan_lock:
        await _run_ram_cache_replan(app)


async def _run_ram_cache_replan(app: FastAPI) -> None:
    """The re-plan arithmetic itself — see ``_replan_ram_cache_once``.

    The startup plan is a snapshot. In the hours since, lanes were put to
    sleep and their weights now sit in host RAM (sleep_l1 keeps them there,
    sleep_l2 keeps the lane process), or lanes were stopped and their RAM is
    free again. Running the same arithmetic against the current MemAvailable
    — and reclaiming what no longer fits — is what makes the cache give RAM
    back instead of holding the bytes it grabbed at boot forever. The growth
    bound is refreshed on the same pass, and models the plan newly admits are
    queued for background re-caching (after a short hold-down) so the cache
    flexes both ways.
    """
    cfg = app.state.config
    model_cache = app.state.model_cache
    if not model_cache.enabled:
        return
    model_profiles = app.state.model_profiles
    lane_manager = app.state.lane_manager

    caps = list(cfg.logos.capabilities_models) if cfg.logos else []
    # Static/live lane models can sleep too: static_lanes may enable sleep mode
    # for models outside capabilities_models, and _add_lane_unlocked caches any
    # vLLM model on demand. Their sleeping residency must enter the reserve, so
    # a static-only worker (empty capabilities_models) still reserves host RAM
    # instead of returning here and leaving the floor unset.
    reserve_models = _sleepable_lane_models(cfg, lane_manager)
    candidates, _uncalibrated = _build_ram_cache_candidates(cfg, model_cache, model_profiles, caps, reserve_models)
    if not candidates:
        # No calibrated capability models and no sleep-capable static/live lane
        # models means an empty reserve and a plan that keeps exactly what it
        # keeps — there is no arithmetic to re-run.
        return

    host_memory = _build_host_memory_summary()
    if host_memory.source != "proc-meminfo" or not host_memory.available_mb:
        # A failed /proc/meminfo read is not a measurement. Feeding the zero
        # into the plan would come out deeply negative and reclaim the whole
        # cache — while the copy path, which fails OPEN on the same failure,
        # keeps refilling it. A periodic corrector skips bad input instead of
        # acting on it.
        logger.debug(
            "RAM cache re-plan skipped: no usable host RAM reading (source=%s)",
            host_memory.source,
        )
        return

    # Models whose lane is asleep right now: their sleeping RAM is already
    # out of MemAvailable, so it must not enter the reserve again —
    # double-counting would shrink the budget by the size of every sleeping
    # model and over-evict, precisely in the situation this loop exists to
    # handle.
    asleep = await lane_manager.sleeping_models()

    plan = plan_cache_order(
        candidates,
        available_host_ram_mb=float(host_memory.available_mb or 0.0),
        safety_margin_mb=_host_ram_safety_margin_mb(host_memory.total_mb),
        # The cache's own footprint is part of the pool it is budgeted
        # against — without it a full cache reports no room and stays full
        # no matter what (see cache_planner.plan_cache_order).
        cache_held_mb=model_cache.held_bytes() / (1024 * 1024),
        asleep=asleep,
    )

    reclaimed = await _apply_ram_cache_plan(model_cache, plan, _lane_models_with_live_processes(lane_manager))
    if reclaimed:
        logger.info(
            "Re-planned RAM cache: host_ram_available=%.0fMB, reserved_for_sleep=%.0fMB "
            "(%d model(s) already asleep, not reserved again), "
            "tmpfs_budget=%.0fMB — reclaimed %d model(s) for the sleep reserve: %s",
            plan.available_host_ram_mb,
            plan.reserved_for_sleep_mb,
            len(plan.asleep),
            plan.sleepable_tmpfs_budget_mb,
            len(reclaimed),
            reclaimed,
        )

    # RAM freed up and the plan admits models the cache no longer holds —
    # queue them so a later wake or cold load finds them in RAM again.
    # start_background_caching extends the queue; it does not replace it.
    # Two dampers keep this honest:
    #  * hold-down — a model must be in the plan for
    #    RAM_CACHE_RECACHE_HOLD_TICKS consecutive ticks, so a model near the
    #    budget line with MemAvailable jittering is not evicted on one tick
    #    and re-queued on the next while its copy takes minutes;
    #  * no re-queue of what the worker already owns (queued or in flight) —
    #    the enqueue would be a no-op, but the log line would not.
    in_plan_ticks: dict[str, int] = app.state.ram_cache_in_plan_ticks
    order = set(plan.order)
    for m in order:
        in_plan_ticks[m] = in_plan_ticks.get(m, 0) + 1
    for m in [m for m in in_plan_ticks if m not in order]:
        del in_plan_ticks[m]
    busy = model_cache.pending_or_caching()
    recache = [
        m
        for m in plan.order
        if not model_cache.is_cached(m) and m not in busy and in_plan_ticks[m] >= RAM_CACHE_RECACHE_HOLD_TICKS
    ]
    if recache:
        logger.info(
            "Re-planned RAM cache: re-caching %d model(s) now that host RAM allows: %s",
            len(recache),
            recache,
        )
        model_cache.start_background_caching(recache)


async def _ram_cache_replan_loop(app: FastAPI) -> None:
    """Periodically re-plan the RAM cache against the live host RAM.

    A tick that fails is a missed re-plan, not a reason to stop trying — the
    next tick re-runs the same cheap arithmetic. Cancellation is re-raised so
    shutdown can observe it.
    """
    while True:
        await asyncio.sleep(RAM_CACHE_REPLAN_INTERVAL_S)
        try:
            await _replan_ram_cache_once(app)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            # A failed re-plan is an operational event, not a debug detail:
            # the cache is left in whatever state the last successful pass
            # produced — potentially oversized while host RAM is under
            # pressure — and nothing else says so.
            logger.warning("RAM cache re-plan failed", exc_info=True)


def _log_storage_layout(cfg) -> None:
    """Log the resolved storage paths for HF + the four compilation/JIT caches.

    Surfaces (a) where the cache root resolves from — env var vs. config field
    vs. ollama-path fallback — and (b) the absolute path each cache will use,
    so a single grep at boot is enough to debug "is X being persisted?"
    questions.
    """
    from logos_worker_node.vllm_process import VllmProcessHandle

    cache_root = VllmProcessHandle._resolve_persistent_cache_root(cfg.engines.ollama)
    if os.environ.get("LOGOS_WORKER_CACHE_ROOT", "").strip():
        source = "LOGOS_WORKER_CACHE_ROOT env var"
    elif cfg.worker.cache_path:
        source = "config.yml worker.cache_path"
    else:
        source = "fallback: engines.ollama.models_path"

    hf_home = os.environ.get("HF_HOME", "").strip() or os.path.join(cache_root, ".hf_cache")
    cache_dir = os.path.join(cache_root, ".cache")
    vllm_cache = os.environ.get("VLLM_CACHE_ROOT", "").strip() or os.path.join(cache_dir, "vllm")
    inductor_cache = os.environ.get("TORCHINDUCTOR_CACHE_DIR", "").strip() or os.path.join(cache_dir, "torch_inductor")
    flashinfer_base = os.environ.get("FLASHINFER_WORKSPACE_BASE", "").strip() or cache_root

    logger.info(
        "\033[1m\033[36m══ STORAGE LAYOUT ══\033[0m\n"
        "  cache root: %s  (%s)\n"
        "    HF_HOME                  → %s\n"
        "    VLLM_CACHE_ROOT          → %s\n"
        "    TORCHINDUCTOR_CACHE_DIR  → %s\n"
        "    FLASHINFER_WORKSPACE_BASE→ %s  (kernels at <base>/.cache/flashinfer/<version>/<sm>/cached_ops/)",
        cache_root,
        source,
        hf_home,
        vllm_cache,
        inductor_cache,
        flashinfer_base,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        cfg = load_config()
    except Exception:
        logger.exception("Failed to load configuration")
        sys.exit(1)

    _log_storage_layout(cfg)

    gpu_collector = GpuMetricsCollector(poll_interval=cfg.worker.gpu_poll_interval)
    await gpu_collector.start()

    # Watchdog for unrecoverable GPU wedges (GSP RPC failure, PCIe drop,
    # cudaErrorDevicesUnavailable). Drives the host through reboot(2) when
    # node_health reports a gpu-* failure for several consecutive ticks.
    # Requires CAP_SYS_BOOT in the container; see compose `cap_add: [SYS_BOOT]`.
    gpu_watchdog = GpuWatchdog(state_dir=get_state_dir())
    await gpu_watchdog.start()

    # Pre-warm FlashInfer JIT kernels (single-process, sequential) so that
    # subsequent vLLM launches — including TP>1 — find cached .so files and
    # skip JIT, avoiding the multi-process compilation race that crashes GPUs.
    # workspace_base is the parent of .cache/flashinfer; flashinfer 0.6.x reads
    # FLASHINFER_WORKSPACE_BASE (not FLASHINFER_JIT_DIR) to relocate its cache.
    # Honor LOGOS_WORKER_CACHE_ROOT first so deployments without ollama can
    # point all worker caches at any persistent path; default to the ollama
    # models_path which is the persistent volume in the standard compose.
    try:
        from logos_worker_node.flashinfer_warmup import warmup as flashinfer_warmup

        workspace_base = os.environ.get("LOGOS_WORKER_CACHE_ROOT", "").strip() or cfg.engines.ollama.models_path
        capability_models = list(cfg.logos.capabilities_models) if cfg.logos else []
        warmup_ok = flashinfer_warmup(workspace_base, model_names=capability_models)
        if not warmup_ok:
            logger.warning("FlashInfer pre-warmup failed; vLLM will JIT-compile on first launch")
    except Exception:
        logger.warning(
            "FlashInfer pre-warmup failed; vLLM will JIT-compile on first launch",
            exc_info=True,
        )

    model_profiles = ModelProfileRegistry(
        state_dir=get_state_dir(),
        model_profile_overrides=cfg.model_profile_overrides,
    )

    # ── tmpfs RAM cache (created before calibration so models can be loaded
    # from RAM during VRAM measurement, then evicted to free space) ──────────
    hf_home = os.environ.get("HF_HOME", os.path.join(cfg.engines.ollama.models_path, ".hf_cache"))
    model_cache = create_model_cache(
        tmpfs_path=os.environ.get("LOGOS_TMPFS_CACHE_PATH", "").strip() or None,
        hf_home=hf_home,
    )

    # Auto-calibration on startup is disabled — the Logos server now drives
    # calibration via start_calibration / stop_calibration commands during the
    # nightly maintenance window.  The _auto_calibrate_if_needed function is
    # kept for the standalone CLI tool path (tools/calibrate_vram_profiles.py).

    if model_cache.enabled:
        caps = list(cfg.logos.capabilities_models) if cfg.logos else []
        if caps:
            candidates, caps_skipped = _build_ram_cache_candidates(cfg, model_cache, model_profiles, caps)
            if caps_skipped:
                logger.info(
                    "Skipping RAM cache for %d uncalibrated model(s) (no profile data — " "will not be served): %s",
                    len(caps_skipped),
                    caps_skipped,
                )

            # Host-RAM-aware cache plan. Goal (per design):
            #   load as many models into the tmpfs cache as possible WITHOUT
            #   lowering the number of models that can sleep simultaneously.
            #
            # plan_cache_order reserves enough host RAM for every sleepable
            # capability model to be in sleep_l1 at the same time, then packs
            # the remaining budget with cache candidates. Unsleepable models
            # are always included (they don't enter the sleep reserve and
            # benefit most from the cache because their only path back to
            # "loaded" is a cold reload from disk). Sleepable models are
            # admitted only while the running tmpfs budget allows. See the
            # full algorithm in cache_planner.py.
            host_memory = _build_host_memory_summary()
            available_host_ram_mb = float(host_memory.available_mb or 0.0)

            # What the cache already holds is part of the pool it is being
            # budgeted against — without it the plan reads MemAvailable after
            # the cache has spent it, concludes there is no room, and leaves
            # a stale cache in place forever. This is what makes the budget
            # able to come out below the current footprint, which is what
            # produces the reclaim below.
            cache_held_mb = model_cache.held_bytes() / (1024 * 1024)
            plan = plan_cache_order(
                candidates,
                available_host_ram_mb=available_host_ram_mb,
                safety_margin_mb=_host_ram_safety_margin_mb(host_memory.total_mb),
                cache_held_mb=cache_held_mb,
            )
            # Bound every later copy by the same arithmetic, checked against
            # live MemAvailable rather than the tmpfs size. The mount is a
            # fixed 400G of a 503G host, so without this the cache's only
            # limit is four fifths of the machine; with it, a lane that puts
            # weights into host RAM shrinks the cache's room immediately and
            # without anyone re-planning. No lanes exist at this point, so
            # nothing is protected (and nobody is asleep — the full reserve
            # applies).
            reclaimed = await _apply_ram_cache_plan(model_cache, plan, protected=set())
            if reclaimed:
                logger.info(
                    "Reclaimed %d model(s) from the RAM cache — outside this plan's "
                    "budget, and the RAM is worth more to the sleep reserve: %s",
                    len(reclaimed),
                    reclaimed,
                )
            logger.info(
                "Cache plan: host_ram_available=%.0fMB + cache_held=%.0fMB, "
                "reserved_for_sleep=%.0fMB (%d sleepable model(s)), "
                "safety_margin=%.0fMB → tmpfs_budget=%.0fMB. Caching %d "
                "unsleepable + %d sleepable, skipping %d sleepable for headroom.",
                plan.available_host_ram_mb,
                plan.cache_held_mb,
                plan.reserved_for_sleep_mb,
                sum(1 for c in candidates if c.can_sleep),
                plan.safety_margin_mb,
                plan.sleepable_tmpfs_budget_mb,
                len(plan.cached_unsleepable),
                len(plan.cached_sleepable),
                len(plan.skipped_sleepable),
            )
            if plan.skipped_sleepable:
                logger.info(
                    "  Skipped sleepable (would compete with sleep reserve): %s",
                    plan.skipped_sleepable,
                )

            if plan.order:
                logger.info(
                    "Pre-populating RAM cache with %d model(s) in the BACKGROUND: %s. "
                    "Startup continues immediately; apply_lanes for these models "
                    "will block on their cache copy only if it's not finished yet.",
                    len(plan.order),
                    plan.order,
                )
                # Fire-and-forget: lane requests that arrive while the
                # worker is still copying will bump their model to the
                # front via LaneManager → ModelRamCache.wait_for_cached.
                model_cache.start_background_caching(plan.order)
            else:
                logger.info("No models eligible to pre-populate into RAM cache")

    lane_manager = LaneManager(
        global_config=cfg.engines.ollama,
        vllm_engine_config=cfg.engines.vllm,
        lane_port_start=cfg.worker.lane_port_start,
        lane_port_end=cfg.worker.lane_port_end,
        nvidia_smi_available=lambda: gpu_collector.available,
        model_profiles=model_profiles,
        gpu_device_count=lambda: gpu_collector.device_count,
        per_gpu_vram_mb=lambda: gpu_collector.per_gpu_vram_mb,
        gpu_snapshot=gpu_collector.get_snapshot,
        gpu_force_poll=gpu_collector.force_poll,
        max_lanes=cfg.worker.max_lanes,
        model_cache=model_cache,
        auto_reboot_on_stuck_gpu=cfg.worker.auto_reboot_on_stuck_gpu,
        reboot_sentinel_path=cfg.worker.reboot_sentinel_path,
        # The reactive half of the RAM-cache re-plan: the moment a lane's
        # weights land in host RAM, the cache re-plans against the new
        # MemAvailable instead of waiting for the next tick. The closure
        # dereferences app.state at call time — so the fields it reads must
        # already exist. They are initialised right below, before the first
        # startup apply_lanes, because a staggered sleep during apply_lanes
        # fires this hook BEFORE the bridge starts, and _notify_lane_slept
        # swallows a missing-state error (silently skipping the reclaim).
        on_lane_slept=lambda: _replan_ram_cache_once(app),
    )

    # Initialise the re-plan's app.state dependencies NOW, before the startup
    # apply_lanes calls below (static lanes, then restored dynamic lanes) can
    # trigger a staggered sleep -> on_lane_slept. See _init_ram_cache_replan_state
    # for why this must precede apply_lanes — a sleep during startup would
    # otherwise invoke the re-plan against missing state and be swallowed.
    _init_ram_cache_replan_state(app, cfg, lane_manager, model_profiles, model_cache)

    # Validate capabilities models at startup (warnings only)
    if cfg.logos and cfg.logos.capabilities_models:
        missing = lane_manager.validate_capabilities(cfg.logos.capabilities_models)
        if missing and cfg.worker.prefetch_missing_models:
            # Fire-and-forget: download missing weights in the background so the
            # worker boots into zero-lane mode immediately and serves the models
            # it already has while the rest stream in.
            asyncio.create_task(_prefetch_missing_models(missing, hf_home))

    # ── Static lanes (pinned, never removed by the capacity planner) ──────
    static_lane_ids: set[str] = set()
    if cfg.static_lanes:
        for sl in cfg.static_lanes:
            static_lane_ids.add(_lane_id_from_config(sl))
        lane_manager.register_static_lanes(static_lane_ids)
        logger.info("Applying %d static lane(s) from config", len(cfg.static_lanes))
        try:
            result = await lane_manager.apply_lanes(cfg.static_lanes)
            if result.errors:
                raise RuntimeError("; ".join(result.errors))
        except Exception:
            logger.exception("Failed to apply static lanes from config")
            await lane_manager.close()
            await gpu_watchdog.stop()
            await gpu_collector.stop()
            raise

    # Drop restored lanes that exceed MAX_LANES — start fresh and let the
    # server re-assign.  This avoids a hard crash from apply_lanes validation.
    # Account for static lanes already occupying slots.
    effective_max_dynamic = cfg.worker.max_lanes - len(static_lane_ids) if cfg.worker.max_lanes > 0 else 0
    # Filter out static lane IDs from restored dynamic lanes to avoid duplicates
    if cfg.lanes and static_lane_ids:
        cfg.lanes = [lc for lc in cfg.lanes if _lane_id_from_config(lc) not in static_lane_ids]

    if cfg.lanes and cfg.worker.max_lanes > 0 and len(cfg.lanes) > effective_max_dynamic:
        logger.warning(
            "config.yml declares %d dynamic lane(s) but MAX_LANES=%d "
            "(%d static lane(s) already active); "
            "dropping all dynamic lanes and starting in zero-lane mode",
            len(cfg.lanes),
            cfg.worker.max_lanes,
            len(static_lane_ids),
        )
        cfg.lanes = []

    if cfg.lanes:
        logger.info("Applying %d lane(s) from config", len(cfg.lanes))
        try:
            result = await lane_manager.apply_lanes(cfg.lanes)
            if result.errors:
                raise RuntimeError("; ".join(result.errors))
        except Exception:
            logger.exception("Failed to apply lanes from config")
            await lane_manager.close()
            await gpu_watchdog.stop()
            await gpu_collector.stop()
            raise
    else:
        caps = cfg.logos.capabilities_models if cfg.logos else []
        logger.info(
            "\033[1m\033[36m══ ZERO-LANE MODE ══\033[0m " "Waiting for server commands. Capabilities: %s",
            caps or "(none)",
        )
        if caps:
            # Merge inline overrides from capabilities_models entries before seeding
            if cfg.logos and cfg.logos.capabilities_overrides:
                model_profiles.add_overrides(cfg.logos.capabilities_overrides)
            model_profiles.seed_capabilities(caps, engine="vllm")
            ready_caps: list[str] = []
            for cap_model in caps:
                p = model_profiles.get_profile(cap_model)
                if p:
                    src = p.residency_source or "unknown"
                    has_profile = (p.base_residency_mb or 0) > 0
                    if has_profile:
                        src_icon = {
                            "calibrated": "\033[32m●\033[0m",  # green  — calibrated
                            "measured": "\033[32m●\033[0m",  # green  — observed
                            "override": "\033[36m●\033[0m",  # cyan   — manual
                        }.get(
                            src, "\033[33m●\033[0m"
                        )  # yellow — other
                        label = src.upper()
                        ready_caps.append(cap_model)
                    else:
                        src_icon = "\033[31m●\033[0m"  # red    — no data
                        label = "UNCALIBRATED"
                    logger.info(
                        "  %s %s [%s]: base_residency=%.0f MB | "
                        "disk=%.1f GB | kv_per_token=%s B | max_ctx=%s | engine=%s",
                        src_icon,
                        cap_model,
                        label,
                        p.base_residency_mb or 0,
                        (p.disk_size_bytes or 0) / (1024**3),
                        p.kv_per_token_bytes,
                        p.max_context_length,
                        p.engine,
                    )

            # Only advertise models with actual profile data to the server
            if len(ready_caps) < len(caps):
                skipped = set(caps) - set(ready_caps)
                logger.warning(
                    "Excluding %d uncalibrated model(s) from capabilities: %s",
                    len(skipped),
                    sorted(skipped),
                )
                cfg.logos.capabilities_models = ready_caps

    app.state.gpu_collector = gpu_collector
    logos_bridge = LogosBridgeClient(app, cfg.logos)
    app.state.logos_bridge = logos_bridge
    await logos_bridge.start()

    # Re-plan the RAM cache against the live host RAM. The startup plan is a
    # snapshot; from here on lanes sleep (weights → host RAM) and stop (RAM
    # free) on the orchestrator's say-so, and the cache has to follow.
    ram_cache_replan_task: asyncio.Task | None = None
    if model_cache.enabled:
        ram_cache_replan_task = asyncio.create_task(_ram_cache_replan_loop(app), name="ram-cache-replan")

    logger.info("LogosWorkerNode started on port %d", cfg.worker.port)
    yield

    logger.info("Shutting down LogosWorkerNode")
    # First: stop the re-plan from touching the cache while lanes are being
    # torn down. A tick mid-shutdown is harmless at worst, but there is no
    # reason to take "worst" for free.
    if ram_cache_replan_task is not None:
        ram_cache_replan_task.cancel()
        try:
            await ram_cache_replan_task
        except (asyncio.CancelledError, Exception):
            pass
    try:
        await logos_bridge.stop()
    except Exception:
        logger.warning("Error stopping Logos bridge", exc_info=True)
    try:
        await asyncio.wait_for(lane_manager.destroy_all(), timeout=_LANE_MANAGER_SHUTDOWN_TIMEOUT)
    except asyncio.TimeoutError:
        logger.error(
            "Timed out destroying lanes after %ss; continuing shutdown with best-effort cleanup",
            _LANE_MANAGER_SHUTDOWN_TIMEOUT,
        )
    except Exception:
        logger.warning("Error destroying lanes", exc_info=True)
    await lane_manager.close()
    await gpu_watchdog.stop()
    await gpu_collector.stop()
    # Cancel any pending background RAM cache copies. Won't roll back an
    # rsync that's already in flight, but stops the worker from queueing
    # more after shutdown was requested.
    try:
        await model_cache.stop_background_caching()
    except Exception:  # noqa: BLE001
        logger.debug("model_cache.stop_background_caching failed", exc_info=True)


def create_app() -> FastAPI:
    app = FastAPI(
        title="LogosWorkerNode",
        description="Lane-based local inference worker for Logos.",
        version=SERVICE_VERSION,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/", tags=["root"])
    async def root() -> dict[str, str]:
        return {
            "service": "LogosWorkerNode",
            "version": SERVICE_VERSION,
            "docs": "/docs",
        }

    return app


app = create_app()


def main() -> None:
    cfg = load_config()
    kwargs: dict[str, object] = {
        "app": "logos_worker_node.main:app",
        "host": "0.0.0.0",
        "port": cfg.worker.port,
        "log_level": "info",
    }
    if cfg.worker.tls_enabled:
        kwargs["ssl_certfile"] = cfg.worker.tls_cert_path
        kwargs["ssl_keyfile"] = cfg.worker.tls_key_path
    uvicorn.run(**kwargs)


if __name__ == "__main__":
    main()

"""Pure shaping of logosnode worker runtime snapshots.

The registry (``logosnode_registry``) holds the raw runtime payload each
worker sends over its websocket session. These functions turn that payload
into the derived views the orchestrator serves: scheduler signals for the
capacity planner, live VRAM samples for the statistics page, per-lane served
context windows, and the worker-safe model-name aliases used in lane ids and
logs.

They deliberately take snapshots as arguments instead of reading the registry
or the database, so they stay unit-testable without a live worker.

One naming trap for tests: ``_logosnode_snapshot_is_connected`` reads
``_LOGOSNODE_STATS_STALE_AFTER_SECONDS`` from *this* module's namespace, not
from ``main``. ``main`` re-imports the same name (it passes it to the
statistics endpoints), so a future ``monkeypatch.setattr(main,
"_LOGOSNODE_STATS_STALE_AFTER_SECONDS", ...)`` would resolve fine and silently
not affect connectedness — patch
``logos.logosnode_snapshot._LOGOSNODE_STATS_STALE_AFTER_SECONDS`` instead.
"""

import datetime
from typing import Any, Dict, Optional

from logos.dbutils.dbmanager import derived_reported_context_length
from logos.timeouts import _env_int

# Kept here (rather than in ``timeouts.py`` with the other ``_LOGOSNODE_*``
# settings) because the snapshot helpers — not the ``main.py`` execution path —
# read it. See the docstring for the monkeypatch trap that creates.
_LOGOSNODE_STATS_STALE_AFTER_SECONDS = _env_int("LOGOSNODE_STATS_STALE_AFTER_SECONDS", 30)


def _parse_iso_datetime(raw: Any) -> Optional[datetime.datetime]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_today_or_all_utc(day: str) -> bool:
    normalized = str(day or "").strip().lower()
    if normalized == "all":
        return True
    return normalized == datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def _logosnode_snapshot_is_connected(snapshot: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(snapshot, dict):
        return False
    last_heartbeat = _parse_iso_datetime(snapshot.get("last_heartbeat"))
    if last_heartbeat is None:
        return False
    now = datetime.datetime.now(datetime.timezone.utc)
    return (now - last_heartbeat) <= datetime.timedelta(seconds=_LOGOSNODE_STATS_STALE_AFTER_SECONDS)


def _normalize_loaded_models(lanes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        lane_model = str(lane.get("model") or "").strip()
        loaded_models = lane.get("loaded_models") or []
        if not isinstance(loaded_models, list):
            loaded_models = []
        for item in loaded_models:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or lane_model).strip()
            if not name:
                continue
            size_vram = int(item.get("size_vram") or 0)
            size_bytes = int(item.get("size") or 0)
            current = deduped.get(name)
            candidate = {
                "name": name,
                "size": size_bytes,
                "size_vram": size_vram,
            }
            if current is None or candidate["size_vram"] > current["size_vram"]:
                deduped[name] = candidate
    return sorted(deduped.values(), key=lambda item: item["name"].lower())


def _planner_model_alias(model_name: str) -> str:
    """Return the planner/worker-safe alias used in lane ids and logs."""
    return str(model_name or "").strip().replace("/", "_").replace(":", "_").replace(" ", "_")


def _resolve_requested_model_name(
    requested_name: str,
    available_models: list[Dict[str, Any]],
) -> Optional[str]:
    """Resolve a user-supplied model id to a canonical DB model name.

    ``available_models`` are the accessible model rows (each with a ``name``
    and, optionally, an ``aliases`` list of stored alternative names).

    Matches, in order of precedence:
    1. the canonical name as stored in the DB,
    2. a stored alias of the model (e.g. a logical tag like
       ``local-most-powerful`` that can be re-pointed at another model),
    3. the planner-safe alias form where ``/``, ``:``, and spaces are
       rewritten as underscores (lets users copy model ids from lane names
       or worker logs without breaking access-controlled model lookup).

    All matching is case-insensitive. Every level must resolve to a single
    unambiguous model to be accepted: the schema does not enforce
    case-insensitive uniqueness of model names, so two models whose names
    only differ in case make a canonical request ambiguous, and a stored
    alias that matches several models does not fall through to the planner
    aliases (a stored name is an explicit assignment and wins over the
    derived form). Ambiguous requests resolve to ``None``.
    """
    requested = str(requested_name or "").strip()
    if not requested:
        return None
    requested_lc = requested.lower()

    canonical_matches: set[str] = set()
    stored_alias_matches: set[str] = set()
    planner_alias_matches: set[str] = set()
    for entry in available_models:
        canonical = str((entry or {}).get("name") or "").strip()
        if not canonical:
            continue
        if canonical.lower() == requested_lc:
            canonical_matches.add(canonical)
            continue

        sanitized = _planner_model_alias(canonical)
        if requested_lc in {sanitized.lower(), f"planner-{sanitized.lower()}"}:
            planner_alias_matches.add(canonical)
        for alias in entry.get("aliases") or []:
            if str(alias).strip().lower() == requested_lc:
                stored_alias_matches.add(canonical)

    if len(canonical_matches) == 1:
        return next(iter(canonical_matches))
    if canonical_matches:
        # duplicate normalized model names — no way to tell which one was meant
        return None
    if len(stored_alias_matches) == 1:
        return next(iter(stored_alias_matches))
    if stored_alias_matches:
        # an ambiguous stored alias must not fall through to planner aliases
        return None
    if len(planner_alias_matches) == 1:
        return next(iter(planner_alias_matches))
    return None


def _runtime_modes_for_lanes(lanes: list[dict[str, Any]]) -> list[str]:
    modes: set[str] = set()
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        modes.add("vllm" if bool(lane.get("vllm")) else "ollama")
    return sorted(modes)


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _merge_histogram_buckets(target: dict[str, float], source: Any) -> None:
    if not isinstance(source, dict):
        return
    for raw_bucket, raw_value in source.items():
        bucket = str(raw_bucket).strip()
        if not bucket:
            continue
        count = _safe_float(raw_value)
        if count is None or count < 0:
            continue
        target[bucket] = target.get(bucket, 0.0) + count


def _histogram_quantile_seconds(histogram: Any, quantile: float = 0.95) -> Optional[float]:
    if not isinstance(histogram, dict) or not histogram:
        return None

    buckets: list[tuple[float, float]] = []
    for raw_bucket, raw_count in histogram.items():
        count = _safe_float(raw_count)
        if count is None or count < 0:
            continue
        bucket_label = str(raw_bucket).strip()
        if not bucket_label:
            continue
        if bucket_label == "+Inf":
            upper_bound = float("inf")
        else:
            upper_bound = _safe_float(bucket_label)
            if upper_bound is None:
                continue
        buckets.append((upper_bound, count))

    if not buckets:
        return None

    buckets.sort(key=lambda item: item[0])
    total_count = max(count for _upper, count in buckets)
    if total_count <= 0:
        return None

    target = total_count * max(0.0, min(1.0, quantile))
    previous_upper = 0.0
    previous_count = 0.0

    for upper_bound, cumulative_count in buckets:
        if cumulative_count < target:
            previous_upper = 0.0 if upper_bound == float("inf") else upper_bound
            previous_count = cumulative_count
            continue

        if upper_bound == float("inf"):
            return previous_upper if previous_upper > 0 else None

        bucket_count = cumulative_count - previous_count
        if bucket_count <= 0:
            return upper_bound

        bucket_width = upper_bound - previous_upper
        if bucket_width <= 0:
            return upper_bound

        fraction = (target - previous_count) / bucket_count
        return previous_upper + (fraction * bucket_width)

    last_upper = buckets[-1][0]
    if last_upper == float("inf"):
        return previous_upper if previous_upper > 0 else None
    return last_upper


def _lane_served_context_window(lane: dict, model_profiles: dict) -> int:
    """Served context window of one lane in tokens, 0 when unknown.

    Mirrors the worker's --max-model-len precedence for vLLM lanes
    (vllm_process.py): explicit vllm_config value, then a non-sentinel lane
    context_length (4096 is the shared lane-schema default, meaning "unset"
    for vLLM), then the calibrated profile value. Ollama lanes always run at
    their configured context_length. A vLLM lane where none of these are set
    lets vLLM pick the model's native maximum, which the worker does not
    report — such lanes yield 0 rather than a guess.
    """
    model = lane.get("model")
    if not model:
        return 0

    def _as_len(value) -> int:
        try:
            value = int(value)
        except (TypeError, ValueError):
            return 0
        return value if value > 0 else 0

    if not lane.get("vllm"):
        return _as_len(lane.get("context_length"))

    backend_metrics = lane.get("backend_metrics")
    explicit = _as_len(backend_metrics.get("max_model_len")) if isinstance(backend_metrics, dict) else 0
    if explicit:
        return explicit
    lane_ctx = _as_len(lane.get("context_length"))
    if lane_ctx and lane_ctx != 4096:
        return lane_ctx
    profile = model_profiles.get(model)
    if isinstance(profile, dict):
        return _as_len(profile.get("calibration_max_model_len")) or _as_len(profile.get("max_context_length"))
    return 0


def _profile_native_context_length(profile: dict) -> int:
    """Largest context window a model could ever be served with here.

    The widest window the model's profile reports — its own architectural
    limit (``max_context_length``), the ``--max-model-len`` calibration settled
    on (``calibration_max_model_len``), or the widest point of the calibrated
    KV sweep — whichever is largest. This is the "all-time maximum" the model
    offers, as opposed to the window a lane happens to run with right now.

    Reading ``calibration_max_model_len`` matters on its own: a model
    calibration capped its ``--max-model-len`` to fit the pinned KV budget and
    recorded no wider KV point, so the calibrated cap is the only context the
    profile reports. Ignoring it made such a model look context-unknown (and
    the client fall back to a guessed window) while its worker sat connected
    and ready to serve it at exactly that width (#829).
    """
    return derived_reported_context_length(profile)


def _build_logosnode_scheduler_signals(runtime: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(runtime, dict):
        return {}

    devices = runtime.get("devices") if isinstance(runtime.get("devices"), dict) else {}
    capacity = runtime.get("capacity") if isinstance(runtime.get("capacity"), dict) else {}
    transport = runtime.get("transport") if isinstance(runtime.get("transport"), dict) else {}
    lanes = runtime.get("lanes") if isinstance(runtime.get("lanes"), list) else []
    # Needed to resolve a lane's served window: a vLLM lane that was started
    # without an explicit --max-model-len takes it from the calibrated profile,
    # so the number is not on the lane itself.
    model_profiles = runtime.get("model_profiles") if isinstance(runtime.get("model_profiles"), dict) else {}

    provider_signals: Dict[str, Any] = {
        "timestamp": runtime.get("timestamp"),
        "transport_connected": bool(transport.get("connected", True)),
        "device_mode": devices.get("mode"),
        "nvidia_smi_available": bool(devices.get("nvidia_smi_available", False)),
        "device_count": (len(devices.get("devices") or []) if isinstance(devices.get("devices"), list) else 0),
        "total_memory_mb": _safe_float(devices.get("total_memory_mb")),
        "used_memory_mb": _safe_float(devices.get("used_memory_mb")),
        "free_memory_mb": _safe_float(devices.get("free_memory_mb")),
        "lane_count": _safe_int(capacity.get("lane_count")) or len(lanes),
        "active_requests": _safe_int(capacity.get("active_requests")) or 0,
        "loaded_lane_count": _safe_int(capacity.get("loaded_lane_count")) or 0,
        "sleeping_lane_count": _safe_int(capacity.get("sleeping_lane_count")) or 0,
        "cold_lane_count": _safe_int(capacity.get("cold_lane_count")) or 0,
        "total_effective_vram_mb": _safe_float(capacity.get("total_effective_vram_mb")) or 0.0,
        "runtime_modes": _runtime_modes_for_lanes(lanes),
    }

    raw_device_list = devices.get("devices") or []
    provider_signals["devices"] = [
        {
            "device_id": d.get("device_id", ""),
            "kind": d.get("kind", "nvidia"),
            "name": d.get("name", ""),
            "memory_used_mb": float(d.get("memory_used_mb") or 0.0),
            "memory_total_mb": float(d.get("memory_total_mb") or 0.0),
            "memory_free_mb": float(d.get("memory_free_mb") or 0.0),
            "utilization_percent": _safe_float(d.get("utilization_percent")),
            "temperature_celsius": _safe_float(d.get("temperature_celsius")),
            "power_draw_watts": _safe_float(d.get("power_draw_watts")),
        }
        for d in raw_device_list
        if isinstance(d, dict)
    ]

    model_signals: dict[str, Dict[str, Any]] = {}
    lane_signals: dict[str, Dict[str, Any]] = {}

    def _ensure_model_entry(model_name: str) -> Dict[str, Any]:
        return model_signals.setdefault(
            model_name,
            {
                "lane_count": 0,
                "vllm_lane_count": 0,
                "ollama_lane_count": 0,
                "loaded_lane_count": 0,
                "running_lane_count": 0,
                "sleeping_lane_count": 0,
                "cold_lane_count": 0,
                "starting_lane_count": 0,
                "error_lane_count": 0,
                "active_requests": 0,
                "effective_vram_mb": 0.0,
                "reported_vram_mb": 0.0,
                "pid_vram_mb": 0.0,
                "device_vram_mb": 0.0,
                "queue_waiting_current": 0.0,
                "requests_running_current": 0.0,
                "prompt_tokens_total": None,
                "generation_tokens_total": None,
                "ttft_histogram": {},
                "ttft_p95_seconds": None,
                "gpu_cache_usage_percent_avg": None,
                "gpu_cache_usage_percent_max": None,
                "prefix_cache_hit_rate_avg": None,
                "mtp_acceptance_rate_avg": None,
                "_gpu_cache_usage_percent_sum": 0.0,
                "_gpu_cache_usage_percent_count": 0,
                "_prefix_cache_hit_rate_sum": 0.0,
                "_prefix_cache_hit_rate_count": 0,
                "_mtp_draft_tokens_total": 0.0,
                "_mtp_accepted_tokens_total": 0.0,
            },
        )

    for lane in lanes:
        if not isinstance(lane, dict):
            continue

        model_name = str(lane.get("model") or "").strip()
        lane_id = str(lane.get("lane_id") or "").strip()
        runtime_state = str(lane.get("runtime_state") or "").strip()
        is_vllm = bool(lane.get("vllm"))
        active_requests = _safe_int(lane.get("active_requests")) or 0
        backend_metrics = lane.get("backend_metrics") if isinstance(lane.get("backend_metrics"), dict) else {}
        ttft_histogram = (
            backend_metrics.get("ttft_histogram") if isinstance(backend_metrics.get("ttft_histogram"), dict) else {}
        )
        lane_ttft_p95 = _histogram_quantile_seconds(ttft_histogram)

        lane_signal = {
            "model": model_name,
            "vllm": is_vllm,
            "runtime_state": runtime_state,
            "sleep_state": lane.get("sleep_state"),
            "gpu_devices": str(lane.get("gpu_devices") or ""),
            "effective_gpu_devices": str(lane.get("effective_gpu_devices") or ""),
            "num_parallel": _safe_int(lane.get("num_parallel")) or 0,
            "active_requests": active_requests,
            "effective_vram_mb": _safe_float(lane.get("effective_vram_mb")) or 0.0,
            "reported_vram_mb": _safe_float(lane.get("reported_vram_mb")) or 0.0,
            "pid_vram_mb": _safe_float(lane.get("pid_vram_mb")) or 0.0,
            "device_vram_mb": _safe_float(lane.get("device_vram_mb")) or 0.0,
            "vram_source": lane.get("vram_source"),
            "queue_waiting": _safe_float(backend_metrics.get("queue_waiting")),
            "requests_running": _safe_float(backend_metrics.get("requests_running")),
            "gpu_cache_usage_percent": _safe_float(backend_metrics.get("gpu_cache_usage_percent")),
            "prefix_cache_hit_rate": _safe_float(backend_metrics.get("prefix_cache_hit_rate")),
            "mtp_acceptance_rate": _safe_float(backend_metrics.get("mtp_acceptance_rate")),
            "prompt_tokens_total": _safe_float(backend_metrics.get("prompt_tokens_total")),
            "generation_tokens_total": _safe_float(backend_metrics.get("generation_tokens_total")),
            "ttft_histogram": ttft_histogram,
            "ttft_p95_seconds": lane_ttft_p95,
            # The window this lane is actually serving at. Two lanes of the same
            # model can differ — the planner sizes each against the KV cache it
            # could get — so it belongs on the lane and not on the model. 0 when
            # the worker reports nothing to derive it from.
            "max_model_len": _lane_served_context_window(lane, model_profiles) or None,
        }
        if lane_id:
            lane_signals[lane_id] = lane_signal

        if not model_name:
            continue

        entry = _ensure_model_entry(model_name)
        entry["lane_count"] += 1
        if is_vllm:
            entry["vllm_lane_count"] += 1
        else:
            entry["ollama_lane_count"] += 1

        if runtime_state == "loaded":
            entry["loaded_lane_count"] += 1
        elif runtime_state == "running":
            entry["running_lane_count"] += 1
        elif runtime_state == "sleeping":
            entry["sleeping_lane_count"] += 1
        elif runtime_state == "cold":
            entry["cold_lane_count"] += 1
        elif runtime_state == "starting":
            entry["starting_lane_count"] += 1
        elif runtime_state == "error":
            entry["error_lane_count"] += 1

        entry["active_requests"] += active_requests
        entry["effective_vram_mb"] += _safe_float(lane.get("effective_vram_mb")) or 0.0
        entry["reported_vram_mb"] += _safe_float(lane.get("reported_vram_mb")) or 0.0
        entry["pid_vram_mb"] += _safe_float(lane.get("pid_vram_mb")) or 0.0
        entry["device_vram_mb"] += _safe_float(lane.get("device_vram_mb")) or 0.0

        queue_waiting = _safe_float(backend_metrics.get("queue_waiting"))
        if queue_waiting is not None:
            entry["queue_waiting_current"] += queue_waiting

        requests_running = _safe_float(backend_metrics.get("requests_running"))
        if requests_running is not None:
            entry["requests_running_current"] += requests_running

        prompt_tokens_total = _safe_float(backend_metrics.get("prompt_tokens_total"))
        if prompt_tokens_total is not None:
            current_prompt = _safe_float(entry.get("prompt_tokens_total")) or 0.0
            entry["prompt_tokens_total"] = current_prompt + prompt_tokens_total

        generation_tokens_total = _safe_float(backend_metrics.get("generation_tokens_total"))
        if generation_tokens_total is not None:
            current_generation = _safe_float(entry.get("generation_tokens_total")) or 0.0
            entry["generation_tokens_total"] = current_generation + generation_tokens_total

        gpu_cache_usage_percent = _safe_float(backend_metrics.get("gpu_cache_usage_percent"))
        if gpu_cache_usage_percent is not None:
            entry["_gpu_cache_usage_percent_sum"] += gpu_cache_usage_percent
            entry["_gpu_cache_usage_percent_count"] += 1
            current_max = _safe_float(entry.get("gpu_cache_usage_percent_max"))
            entry["gpu_cache_usage_percent_max"] = (
                gpu_cache_usage_percent if current_max is None else max(current_max, gpu_cache_usage_percent)
            )

        prefix_cache_hit_rate = _safe_float(backend_metrics.get("prefix_cache_hit_rate"))
        if prefix_cache_hit_rate is not None:
            entry["_prefix_cache_hit_rate_sum"] += prefix_cache_hit_rate
            entry["_prefix_cache_hit_rate_count"] += 1

        # Token-weighted MTP aggregation: sum the cumulative draft/accepted
        # token counters per model (an unweighted mean of per-lane rates would
        # misstate the model rate when lanes have different draft volumes).
        mtp_draft_tokens_total = _safe_float(backend_metrics.get("mtp_draft_tokens_total"))
        if mtp_draft_tokens_total is not None:
            entry["_mtp_draft_tokens_total"] += mtp_draft_tokens_total

        mtp_accepted_tokens_total = _safe_float(backend_metrics.get("mtp_accepted_tokens_total"))
        if mtp_accepted_tokens_total is not None:
            entry["_mtp_accepted_tokens_total"] += mtp_accepted_tokens_total

        _merge_histogram_buckets(entry["ttft_histogram"], ttft_histogram)

    for entry in model_signals.values():
        gpu_count = int(entry.pop("_gpu_cache_usage_percent_count", 0) or 0)
        gpu_sum = float(entry.pop("_gpu_cache_usage_percent_sum", 0.0) or 0.0)
        if gpu_count > 0:
            entry["gpu_cache_usage_percent_avg"] = gpu_sum / gpu_count

        prefix_count = int(entry.pop("_prefix_cache_hit_rate_count", 0) or 0)
        prefix_sum = float(entry.pop("_prefix_cache_hit_rate_sum", 0.0) or 0.0)
        if prefix_count > 0:
            entry["prefix_cache_hit_rate_avg"] = prefix_sum / prefix_count

        mtp_draft = float(entry.pop("_mtp_draft_tokens_total", 0.0) or 0.0)
        mtp_accepted = float(entry.pop("_mtp_accepted_tokens_total", 0.0) or 0.0)
        if mtp_draft > 0:
            entry["mtp_acceptance_rate_avg"] = mtp_accepted / mtp_draft

        entry["ttft_p95_seconds"] = _histogram_quantile_seconds(entry.get("ttft_histogram"))

    return {
        "provider": provider_signals,
        "models": model_signals,
        "lanes": lane_signals,
    }


def _build_live_local_provider_sample(
    provider: Optional[Dict[str, Any]],
    snapshot: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not _logosnode_snapshot_is_connected(snapshot):
        return None

    runtime = snapshot.get("runtime") if isinstance(snapshot, dict) else {}
    if not isinstance(runtime, dict):
        return None

    lanes = runtime.get("lanes") if isinstance(runtime.get("lanes"), list) else []
    devices = runtime.get("devices") if isinstance(runtime.get("devices"), dict) else {}
    capacity = runtime.get("capacity") if isinstance(runtime.get("capacity"), dict) else {}
    transport = runtime.get("transport") if isinstance(runtime.get("transport"), dict) else {}

    used_vram_mb = float(devices.get("used_memory_mb") or 0.0)
    if used_vram_mb <= 0:
        used_vram_mb = float(capacity.get("total_effective_vram_mb") or 0.0)

    total_vram_mb = float(devices.get("total_memory_mb") or 0.0)
    if total_vram_mb <= 0 and isinstance(provider, dict) and provider.get("total_vram_mb") is not None:
        total_vram_mb = float(provider.get("total_vram_mb") or 0.0)

    remaining_vram_mb: Optional[float] = None
    if devices.get("nvidia_smi_available"):
        remaining_vram_mb = float(devices.get("free_memory_mb") or 0.0)
    elif total_vram_mb > 0:
        remaining_vram_mb = max(total_vram_mb - used_vram_mb, 0.0)

    loaded_models = _normalize_loaded_models(lanes)
    runtime_modes = _runtime_modes_for_lanes(lanes)
    scheduler_signals = _build_logosnode_scheduler_signals(runtime)

    if remaining_vram_mb is None and not loaded_models and used_vram_mb <= 0:
        return None

    # Pick the freshest timestamp the worker has given us. With an idle
    # cluster the cached `runtime.timestamp` can be hours old (the worker
    # only emits status on lane-state changes), while `last_heartbeat`
    # advances on every WS heartbeat. Using the older of the two would
    # collide with the already-persisted DB sample inside
    # _merge_provider_samples and add no new point — leaving the chart
    # with a single dot that scatter `mode: "lines"` can't draw.
    runtime_ts = runtime.get("timestamp") if isinstance(runtime.get("timestamp"), str) else None
    heartbeat_ts = snapshot.get("last_heartbeat") if isinstance(snapshot, dict) else None
    if isinstance(heartbeat_ts, datetime.datetime):
        heartbeat_ts = heartbeat_ts.isoformat()
    elif not isinstance(heartbeat_ts, str):
        heartbeat_ts = None
    candidates = [t for t in (heartbeat_ts, runtime_ts) if isinstance(t, str) and t.strip()]
    # Pick the freshest by comparing instants, not strings: runtime.timestamp
    # arrives Pydantic-serialized with a "Z" suffix while last_heartbeat is
    # isoformat()-ed with "+00:00", so a lexicographic max() picks the wrong
    # one whenever one side omits fractional seconds and the suffixes diverge
    # (a newer ...00.001+00:00 loses to an older ...00Z). Parse each candidate,
    # keep the latest instant, and serialize it the way the fallback below does.
    parsed = []
    for t in candidates:
        d = _parse_iso_datetime(t)
        if d is None:
            continue
        if d.tzinfo is None:
            # Naive input would make max() raise TypeError against an
            # aware candidate; the whole pipeline treats timestamps as
            # UTC, so normalize rather than crash.
            d = d.replace(tzinfo=datetime.timezone.utc)
        parsed.append(d)
    timestamp = max(parsed).isoformat() if parsed else datetime.datetime.now(datetime.timezone.utc).isoformat()

    return {
        "timestamp": timestamp,
        "snapshot_source": "logosnode-runtime",
        "provider_type": (provider.get("provider_type") if isinstance(provider, dict) else "logosnode"),
        "connection_state": "online",
        "connected": True,
        "transport_connected": bool(transport.get("connected", True)),
        "runtime_modes": runtime_modes,
        "vram_mb": used_vram_mb,
        "used_vram_mb": used_vram_mb,
        "remaining_vram_mb": remaining_vram_mb,
        "total_vram_mb": total_vram_mb if total_vram_mb > 0 else None,
        "models_loaded": len(loaded_models),
        "loaded_models": loaded_models,
        "runtime_payload": runtime,
        "scheduler_signals": scheduler_signals,
    }


def _sample_snapshot_id(sample: Dict[str, Any]) -> int:
    try:
        return int(sample.get("snapshot_id") or 0)
    except (TypeError, ValueError):
        return 0


def _sample_sort_key(sample: Dict[str, Any]) -> tuple[int, str]:
    return (_sample_snapshot_id(sample), str(sample.get("timestamp") or ""))


def _merge_provider_samples(
    existing_samples: list[Dict[str, Any]],
    extra_samples: list[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    by_key: dict[str, Dict[str, Any]] = {}
    for sample in list(existing_samples) + list(extra_samples):
        if not isinstance(sample, dict):
            continue
        key = str(sample.get("snapshot_id") or sample.get("timestamp") or "")
        if not key:
            continue
        by_key[key] = {**by_key.get(key, {}), **sample}
    return sorted(by_key.values(), key=_sample_sort_key)

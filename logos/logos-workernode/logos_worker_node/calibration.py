"""Shared calibration engine for VRAM profiling.

Extracts the reusable calibration functions so they can be imported both by
the standalone CLI tool (``tools/calibrate_vram_profiles.py``) and by the
worker's startup flow (``main.py``).

The calibration process sweeps KV cache sizes upward (starting at
``_KV_CACHE_MIN_STEP_MB`` floor, up to ``_KV_CACHE_VRAM_CAP_RATIO`` of
per-GPU VRAM in ``_KV_CACHE_MIN_STEP_MB`` steps) and records the
``(kv_cache_mb, max_model_len)`` curve. It measures real VRAM in awake and
sleeping states and persists the results to ``model_profiles.yml``.

VRAM decomposition (exact, no guessing)::

    base_residency_mb    = loaded_vram_mb  (weights + KV cache — full footprint)
    sleeping_residual_mb = measured directly after sleep
    kv_budget_mb         = kv_cache_sent_mb (stored for auditing only)

The scheduler uses ``base_residency_mb`` directly for calibrated profiles — it
does NOT add a separate KV estimate on top.  For uncalibrated profiles the
scheduler falls back to ``base_residency + estimated_kv``.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

try:
    import yaml

    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_VLLM = "vllm"
_READY_TIMEOUT_S = 600.0
_SLEEP_TIMEOUT_S = 120.0
_VLLM_STOP_TIMEOUT_S = 30.0
_VRAM_SETTLE_S = 4.0
_VRAM_SAMPLE_COUNT = 3
_VRAM_SAMPLE_INTERVAL_S = 1.0
_PROFILES_FILE = "model_profiles.yml"
_CALIBRATION_PORT = 11499
_KV_CACHE_MIN_STEP_MB = 1024.0  # sweep step and safety margin
_KV_CACHE_VRAM_CAP_RATIO = 0.8  # fraction of total GPU VRAM used as KV search ceiling
_FINAL_MEASUREMENT_RETRIES = 3  # retries for the final VRAM measurement startup
_FAILED_COMMANDS_FILE = "calibration_failed_commands.txt"
_SUCCEEDED_COMMANDS_FILE = "calibration_succeeded_commands.txt"
_UNSUPPORTED_MODELS_FILE = "calibration_unsupported_models.txt"

# ---------------------------------------------------------------------------
# ANSI colours for calibration search visualisation
# ---------------------------------------------------------------------------

_C_RESET = "\033[0m"
_C_GREEN = "\033[32m"  # success / best
_C_RED = "\033[31m"  # failure
_C_YELLOW = "\033[33m"  # blacklisted (skipped)
_C_CYAN = "\033[36m"  # whitelisted (instant OK)
_C_DIM = "\033[2m"  # untested
_C_BOLD = "\033[1m"
_C_GREEN_BG = "\033[42;30m"  # best marker


def _render_search_bar(
    floor_mb: float,
    ceiling_mb: float,
    step_mb: float,
    probes: dict[float, str],  # kv_mb → "ok" | "fail" | "skip" | "whitelist" | "best"
    best_kv: float | None = None,
) -> str:
    """Render a coloured ASCII bar showing the KV cache search state.

    Example output::

      1G [··✗··✓··✓·✗★·✗··✗···] 38G   best=18G
           ↑fail  ↑ok      ↑best
    """
    slots: list[float] = []
    kv = floor_mb
    while kv <= ceiling_mb:
        slots.append(kv)
        kv += step_mb

    bar_chars: list[str] = []
    for s in slots:
        status = probes.get(s)
        if best_kv is not None and s == best_kv:
            bar_chars.append(f"{_C_GREEN_BG}★{_C_RESET}")
        elif status == "ok" or status == "whitelist":
            c = _C_CYAN if status == "whitelist" else _C_GREEN
            bar_chars.append(f"{c}✓{_C_RESET}")
        elif status == "fail":
            bar_chars.append(f"{_C_RED}✗{_C_RESET}")
        elif status == "skip":
            bar_chars.append(f"{_C_YELLOW}─{_C_RESET}")
        else:
            bar_chars.append(f"{_C_DIM}·{_C_RESET}")

    bar = "".join(bar_chars)
    lo_label = _format_kv_mb(floor_mb)
    hi_label = _format_kv_mb(ceiling_mb)
    best_label = f"  best={_C_BOLD}{_C_GREEN}{_format_kv_mb(best_kv)}{_C_RESET}" if best_kv else ""
    return f"  {lo_label} [{bar}] {hi_label}{best_label}"


# ---------------------------------------------------------------------------
# KV-cache size parsing
# ---------------------------------------------------------------------------


def _parse_kv_to_mb(value: str) -> float:
    """Parse a human-friendly size string to megabytes.

    ``'4G'`` → 4096.0, ``'512M'`` → 512.0, ``'1024'`` (bytes) → ~0.001.
    """
    v = (value or "").strip().upper()
    if v.endswith("G"):
        return float(v[:-1]) * 1024.0
    if v.endswith("M"):
        return float(v[:-1])
    if v.endswith("K"):
        return float(v[:-1]) / 1024.0
    return float(v) / (1024.0 * 1024.0)  # raw bytes


def _format_kv_mb(mb: float) -> str:
    """Format a megabyte value as a human-friendly KV cache size string.

    ``2048.0`` → ``'2G'``, ``1536.0`` → ``'1536M'``.
    """
    if mb >= 1024.0 and mb % 1024.0 == 0:
        return f"{int(mb / 1024)}G"
    return f"{int(mb)}M"


def _round_up_gb(mb: float) -> float:
    """Round *mb* up to the nearest whole gigabyte (1024 MB boundary)."""
    return math.ceil(mb / 1024.0) * 1024.0


# ---------------------------------------------------------------------------
# Failed-command blacklist
# ---------------------------------------------------------------------------


def _cmd_fingerprint(cmd: list[str]) -> str:
    """Build a canonical one-line string from a vLLM command list.

    Strips ``--host`` and ``--port`` (calibration infra, not model-specific)
    so that retries on a different port aren't falsely considered "new".
    """
    filtered: list[str] = []
    skip_next = False
    for tok in cmd:
        if skip_next:
            skip_next = False
            continue
        if tok in ("--host", "--port"):
            skip_next = True
            continue
        filtered.append(tok)
    return " ".join(filtered)


def _load_failed_commands(failed_path: Path) -> set[str]:
    if not failed_path.exists():
        return set()
    return {
        line.strip()
        for line in failed_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def _record_failed_command(failed_path: Path, fingerprint: str) -> None:
    failed_path.parent.mkdir(parents=True, exist_ok=True)
    with failed_path.open("a", encoding="utf-8") as f:
        f.write(fingerprint + "\n")
    logger.info("  Blacklisted command → %s", failed_path)


def _load_succeeded_commands(succeeded_path: Path) -> set[str]:
    if not succeeded_path.exists():
        return set()
    return {
        line.strip()
        for line in succeeded_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def _record_succeeded_command(succeeded_path: Path, fingerprint: str) -> None:
    succeeded_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_succeeded_commands(succeeded_path)
    if fingerprint not in existing:
        with succeeded_path.open("a", encoding="utf-8") as f:
            f.write(fingerprint + "\n")


def _remove_failed_command(failed_path: Path, fingerprint: str) -> None:
    """Remove a fingerprint from the blacklist file (whitelisted success overrides)."""
    if not failed_path.exists():
        return
    lines = failed_path.read_text(encoding="utf-8").splitlines()
    remaining = [ln for ln in lines if ln.strip() != fingerprint]
    if len(remaining) < len(lines):
        failed_path.write_text("\n".join(remaining) + ("\n" if remaining else ""), encoding="utf-8")


# ---------------------------------------------------------------------------
# Model-level "do not retry" blacklist
#
# The per-command blacklist above records (model, tp, kv_cache, …) tuples that
# OOMed. That works for kv-size-sensitive failures: shrink the kv and retry.
#
# But some failures are kv-independent and tied to the model identity itself:
# wrong HuggingFace repo id, missing config.json, gated repo with no token,
# architecture vLLM doesn't recognise. Probing other kv sizes can't fix them —
# each probe just produces an identical failure and adds another junk line to
# the per-command blacklist (and another stuck-GPU recovery to vLLM's restart
# logic). We need a coarser "do not retry this MODEL at all" record.
#
# Adding a pattern: append to ``_FATAL_LOAD_ERROR_PATTERNS`` below. Keep
# patterns NARROW — only error signatures that prove the failure is (a)
# deterministic, (b) about the model itself (not the GPU or vLLM version
# or some transient I/O issue), and (c) unfixable by kv-cache tuning.
# When in doubt, leave it out — a missed pattern just means we waste one
# more calibration window; an over-eager one permanently parks a model
# that would have worked with smaller kv.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FatalLoadErrorPattern:
    """A vLLM log signature that proves the model can never load on this worker.

    Matched as a substring against the vLLM log tail captured after a probe
    failure. Case-sensitive — vLLM's own error strings are stable, so
    fuzzy-matching is unnecessary and just invites false positives.
    """

    needle: str
    reason_code: str  # short, kebab-case; surfaced in logs and the persisted file
    description: str  # human-readable, shown to ops in the file and in error responses


_FATAL_LOAD_ERROR_PATTERNS: tuple[FatalLoadErrorPattern, ...] = (
    FatalLoadErrorPattern(
        needle="Invalid repository ID or local directory specified",
        reason_code="invalid-repo-id",
        description=(
            "vLLM cannot resolve the model name to either a Hugging Face "
            "repository or a local directory containing config.json. The "
            "identifier is misspelled, the repository is private/withdrawn, "
            "or the local directory is missing config.json / params.json."
        ),
    ),
    FatalLoadErrorPattern(
        needle="Cannot access gated repo",
        reason_code="gated-repo-no-token",
        description=(
            "Hugging Face flags this repository as gated. The worker has no "
            "HF token (or the token lacks access). Fix by adding a "
            "HUGGING_FACE_HUB_TOKEN with read access to the repo before "
            "removing this entry."
        ),
    ),
    FatalLoadErrorPattern(
        needle="does not recognize this architecture",
        reason_code="unsupported-architecture",
        description=(
            "The installed vLLM build does not implement this model's "
            "architecture. Upgrade vLLM (and remove this entry) if support "
            "has been added since this worker was deployed."
        ),
    ),
)


def _classify_fatal_load_error(log_tail: str) -> FatalLoadErrorPattern | None:
    """Return the first matching :class:`FatalLoadErrorPattern`, or None.

    Conservative by design: only patterns explicitly listed in
    ``_FATAL_LOAD_ERROR_PATTERNS`` qualify. CUDA OOM, network blips, NCCL
    handshake failures, and other transient/recoverable issues deliberately
    don't match — the kv-cache binary search exists to handle those.
    """
    if not log_tail:
        return None
    for pattern in _FATAL_LOAD_ERROR_PATTERNS:
        if pattern.needle in log_tail:
            return pattern
    return None


@dataclass(frozen=True)
class UnsupportedModelEntry:
    """One line in ``calibration_unsupported_models.txt``.

    Lines are tab-separated::

        <model_name>\\t<reason_code>\\t<recorded_at>\\t<description>

    Lines starting with '#' or blank lines are treated as comments. Multiple
    lines for the same model are tolerated on read — the most recent wins.
    Operators clean up entries by deleting the relevant lines when the
    underlying issue is fixed (bad model name corrected, gated-repo token
    added, vLLM upgraded, …).
    """

    model: str
    reason_code: str
    recorded_at: str  # ISO-8601 UTC, e.g. "2026-06-04T19:46:51Z"
    description: str

    def to_line(self) -> str:
        # Defensive: strip embedded tabs/newlines so a misformatted
        # description can never corrupt the file format.
        def _safe(s: str) -> str:
            return s.replace("\t", " ").replace("\n", " ").strip()

        return "\t".join(
            (
                _safe(self.model),
                _safe(self.reason_code),
                _safe(self.recorded_at),
                _safe(self.description),
            )
        )


def _load_unsupported_models(path: Path) -> dict[str, UnsupportedModelEntry]:
    """Read the unsupported-models file, keyed by model name (latest entry wins)."""
    if not path.exists():
        return {}
    entries: dict[str, UnsupportedModelEntry] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            # Tolerate older/partial lines — best-effort upgrade in-place.
            model = parts[0].strip() if parts else ""
            if not model:
                continue
            entries[model] = UnsupportedModelEntry(
                model=model,
                reason_code=parts[1].strip() if len(parts) > 1 else "unknown",
                recorded_at=parts[2].strip() if len(parts) > 2 else "",
                description=parts[3].strip() if len(parts) > 3 else "",
            )
            continue
        entries[parts[0].strip()] = UnsupportedModelEntry(
            model=parts[0].strip(),
            reason_code=parts[1].strip(),
            recorded_at=parts[2].strip(),
            description=parts[3].strip(),
        )
    return entries


_UNSUPPORTED_FILE_HEADER = (
    "# calibration_unsupported_models.txt — models that calibration will never\n"
    "# retry on this worker until an operator removes the relevant line.\n"
    "#\n"
    "# Format (tab-separated):\n"
    "#   <model_name>\\t<reason_code>\\t<iso_timestamp>\\t<description>\n"
    "#\n"
    "# Reason codes are defined by FatalLoadErrorPattern.reason_code in\n"
    "# logos_worker_node/calibration.py. Remove a line after fixing the\n"
    "# underlying issue (e.g. wrong model name corrected in config.yml,\n"
    "# gated-repo HF token added, vLLM upgraded) to let the next maintenance\n"
    "# window pick the model up again.\n"
)


def _record_unsupported_model(path: Path, entry: UnsupportedModelEntry) -> None:
    """Persist *entry*. If the model is already present, leave the existing
    line in place and append a new one — keeping prior diagnostic context
    visible to operators without duplicating the read-side dedup logic.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(_UNSUPPORTED_FILE_HEADER, encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write(entry.to_line() + "\n")
    logger.warning(
        "  Recorded model-level unsupported entry → %s  (%s, %s)",
        path,
        entry.model,
        entry.reason_code,
    )


def _remove_unsupported_model(path: Path, model: str) -> int:
    """Remove all entries for *model* from the file. Returns the number of
    lines removed. Used when calibration succeeds despite a prior entry
    (operator manually cleared the underlying issue and re-ran).
    """
    if not path.exists():
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    remaining: list[str] = []
    removed = 0
    for ln in lines:
        stripped = ln.strip()
        if not stripped or stripped.startswith("#"):
            remaining.append(ln)
            continue
        head = stripped.split("\t", 1)[0].strip()
        if head == model:
            removed += 1
            continue
        remaining.append(ln)
    if removed:
        path.write_text("\n".join(remaining) + ("\n" if remaining else ""), encoding="utf-8")
    return removed


def is_model_unsupported(log_dir: Path, model: str) -> UnsupportedModelEntry | None:
    """Public helper for callers outside this module (e.g. logos_bridge).

    Returns the most recent :class:`UnsupportedModelEntry` for *model*, or
    None if the model has no entry on this worker.
    """
    path = log_dir / _UNSUPPORTED_MODELS_FILE
    return _load_unsupported_models(path).get(model)


# ---------------------------------------------------------------------------
# Node-level transient failures (storage EIO, fs read-only, etc.)
#
# Unlike _FATAL_LOAD_ERROR_PATTERNS (which marks the *model* permanently
# unsupported), these patterns indicate the *node* is in a degraded state
# that affects every model on it. Examples we've actually seen in prod:
#
#   - Ceph RBD-backed nbd0 device remounted read-only after a network
#     blip → every HF cache directory read returns EIO → 86 garbage
#     entries added to calibration_failed_commands.txt in ~10 minutes
#     before we caught it (deioma, 2026-06-04).
#
# When _try_start sees one of these in the vLLM log tail, it MUST NOT:
#   - write to the per-command blacklist (calibration_failed_commands.txt)
#   - write to the per-model unsupported list (calibration_unsupported_models.txt)
#
# It SHOULD:
#   - log loudly (this will surface in worker logs and, via the bridge,
#     server logs too — feature #3 wires this through the heartbeat to
#     the master so the orchestrator stops scheduling calibrations on
#     unhealthy nodes),
#   - abort the kv-cache search immediately (every probe will fail
#     identically until the underlying issue is fixed),
#   - return a CalibrationResult with ``node_unhealthy_reason`` set so
#     the bridge can update node health state in the runtime status.
#
# Adding a pattern: append to ``_NODE_LEVEL_TRANSIENT_PATTERNS`` below.
# Keep patterns NARROW — only signatures that are unambiguously
# node-environment-level (storage, kernel, hardware), never a vLLM
# argument or model identity issue. When in doubt, leave it out.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NodeTransientErrorPattern:
    """A vLLM (or kernel-surfaced) log signature pointing at node-level
    degradation that no kv-cache probe can recover from.

    Matched as a substring against the vLLM log tail captured after a
    probe failure. Case-sensitive.
    """

    needle: str
    reason_code: str  # short kebab-case identifier surfaced in worker + master logs
    description: str  # human-readable, shown to ops


_NODE_LEVEL_TRANSIENT_PATTERNS: tuple[NodeTransientErrorPattern, ...] = (
    NodeTransientErrorPattern(
        # Kernel reports EIO when the backing device returns hard read errors
        # (bad disk, network block device that lost its OSD, Ceph PG in
        # recovery, …). Files exist on the filesystem but reading them
        # returns Errno 5.
        needle="Input/output error",
        reason_code="filesystem-eio",
        description=(
            "Filesystem reads are failing with EIO (Errno 5). The backing "
            "storage is degraded or disconnected. Investigate the device "
            "(e.g. `dmesg | grep -E 'nbd|EXT4'`, `findmnt`) and restore "
            "connectivity or reboot the node."
        ),
    ),
    NodeTransientErrorPattern(
        # Less common — usually reads (EIO) appear before writes. Kept
        # because it's the unambiguous "kernel remounted r/o" signal.
        needle="Read-only file system",
        reason_code="filesystem-readonly",
        description=(
            "The kernel remounted the filesystem read-only after I/O "
            "errors. The node cannot write to its model cache, profile "
            "store, or calibration logs. Investigate and remount (or "
            "reboot the node)."
        ),
    ),
)


def _classify_node_transient_error(log_tail: str) -> NodeTransientErrorPattern | None:
    """Return the first matching :class:`NodeTransientErrorPattern`, or None.

    Conservative by design: only patterns explicitly listed above qualify.
    Real OOM, network blips between vLLM ranks, NCCL handshake failures,
    etc. are NOT covered — those are recoverable / non-deterministic
    enough that the kv-cache search is still the right response.
    """
    if not log_tail:
        return None
    for pattern in _NODE_LEVEL_TRANSIENT_PATTERNS:
        if pattern.needle in log_tail:
            return pattern
    return None


# vLLM raises a specific ValueError when the configured KV cache budget is too
# small to serve a single request at the model's default max_seq_len, e.g.::
#
#     ValueError: To serve at least one request with the model's max seq len
#     (131072), (8.0 GiB KV cache is needed, which is larger than the available
#     KV cache memory (6.0 GiB). Based on the available memory, the estimated
#     maximum model length is 98304.
#
# This is recoverable WITHOUT enlarging the KV budget: pass --max-model-len at
# the suggested value (or below). The calibration probe loop uses this helper
# to extract the number and auto-retry the same kv_mb with the suggestion
# injected, instead of blacklisting the command and failing the model.
_VLLM_MAX_MODEL_LEN_SUGGESTION_RE = re.compile(r"estimated maximum model length is (\d+)")
_VLLM_MAX_SEQ_LEN_RE = re.compile(r"max seq len \((\d+)\)")
_VLLM_MAX_MODEL_LEN_CONFIG_RE = re.compile(r"max_model_len\s*[=:]\s*(\d+)")
# "... the model's max seq len (131072), 8.94 GiB KV cache is needed ..." — the
# KV required to serve the model's FULL context. With the max seq len this gives
# the KV→context rate, letting the sweep COMPUTE the curve instead of crawling.
_VLLM_KV_GIB_NEEDED_RE = re.compile(r"([\d.]+)\s*GiB KV cache is needed")


def _extract_vllm_kv_gib_needed_for_full(log_tail: str) -> float | None:
    """GiB of KV cache vLLM says it needs to serve the model's full max seq len."""
    m = _VLLM_KV_GIB_NEEDED_RE.search(log_tail)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _extract_vllm_max_model_len_suggestion(log_tail: str) -> int | None:
    """Return vLLM's suggested ``--max-model-len`` when the KV budget is too
    small for the model's default max_seq_len, otherwise None.
    """
    if not log_tail:
        return None
    m = _VLLM_MAX_MODEL_LEN_SUGGESTION_RE.search(log_tail)
    if not m:
        return None
    try:
        value = int(m.group(1))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _extract_vllm_max_seq_len(log_tail: str) -> int | None:
    """Return the model's default max seq len mentioned by vLLM, if present.

    This appears in KV-too-small startup failures and lets calibration record
    the plateau ``max_model_len`` once the default fits again.
    """
    if not log_tail:
        return None
    m = _VLLM_MAX_SEQ_LEN_RE.search(log_tail)
    if not m:
        m = _VLLM_MAX_MODEL_LEN_CONFIG_RE.search(log_tail)
    if not m:
        return None
    try:
        value = int(m.group(1))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


# Hybrid Mamba/SSM models (Qwen3-Coder-Next, …) allocate a fixed pool of
# state-cache blocks sized from the leftover VRAM after weights + KV. Each
# in-flight decode sequence needs one block, so when max_num_seqs (vLLM's
# default 1024) exceeds the pool, CUDA-graph capture aborts at startup with:
#
#     RuntimeError: ... 'max_num_seqs (1024) exceeds available Mamba cache
#     blocks (160). Each decode sequence requires one Mamba cache block, so
#     CUDA graph capture cannot proceed. Please lower max_num_seqs to at most
#     160 or increase gpu_memory_utilization.'
#
# Recoverable by passing --max-num-seqs at (or below) the suggested ceiling.
# The probe loop extracts the number and auto-retries the same kv_mb with the
# flag injected, instead of blacklisting the command and failing the model.
_VLLM_MAX_NUM_SEQS_SUGGESTION_RE = re.compile(r"lower max_num_seqs to at most (\d+)")


def _extract_vllm_max_num_seqs_suggestion(log_tail: str) -> int | None:
    """Return vLLM's suggested ``--max-num-seqs`` ceiling when a hybrid
    Mamba/SSM model's state-cache pool is smaller than max_num_seqs, else None.
    """
    if not log_tail:
        return None
    m = _VLLM_MAX_NUM_SEQS_SUGGESTION_RE.search(log_tail)
    if not m:
        return None
    try:
        value = int(m.group(1))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


# vLLM prints the achievable concurrency at every engine init, e.g.
#   "Maximum concurrency for 33,888 tokens per request: 2.00x"
# This is total_kv_cache_tokens / max_model_len — i.e. how many simultaneous
# full-context requests the KV pool can serve. We read it back (rather than
# pinning --max-num-seqs) to record the "parallelity factor" of each KV point.
_VLLM_MAX_CONCURRENCY_RE = re.compile(r"Maximum concurrency for [\d,]+ tokens per request:\s*([\d.]+)x")


def _extract_vllm_max_concurrency(log_tail: str) -> float | None:
    """Return vLLM's reported achievable concurrency (the ``X.XXx`` factor), else None.

    Uses the LAST occurrence in the log so a re-probe at a different KV size
    reflects the final successful load rather than an earlier attempt.
    """
    if not log_tail:
        return None
    matches = _VLLM_MAX_CONCURRENCY_RE.findall(log_tail)
    if not matches:
        return None
    try:
        value = float(matches[-1])
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


# ---------------------------------------------------------------------------
# GPU VRAM helpers
# ---------------------------------------------------------------------------


def query_gpu_vram(
    gpu_indices: list[int] | None = None,
) -> dict[int, dict[str, float]]:
    """Return per-GPU VRAM snapshot.  *gpu_indices=None* means all GPUs."""
    raw = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=index,memory.total,memory.used,memory.free",
            "--format=csv,noheader,nounits",
        ],
        text=True,
        timeout=30,
    )
    result: dict[int, dict[str, float]] = {}
    for line in raw.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        idx = int(parts[0])
        if gpu_indices is not None and idx not in gpu_indices:
            continue
        result[idx] = {
            "total_mb": float(parts[1]),
            "used_mb": float(parts[2]),
            "free_mb": float(parts[3]),
        }
    return result


def _total_used_mb(snapshot: dict[int, dict[str, float]]) -> float:
    return sum(v["used_mb"] for v in snapshot.values())


def sample_vram_mb(gpu_indices: list[int] | None) -> float:
    """Median VRAM used across target GPUs from *N* samples."""
    samples: list[float] = []
    for i in range(_VRAM_SAMPLE_COUNT):
        samples.append(_total_used_mb(query_gpu_vram(gpu_indices)))
        if i < _VRAM_SAMPLE_COUNT - 1:
            time.sleep(_VRAM_SAMPLE_INTERVAL_S)
    samples.sort()
    return samples[len(samples) // 2]


def parse_gpu_indices(gpu_devices: str) -> list[int] | None:
    """``'0,1'`` → ``[0, 1]``; ``''`` or ``'all'`` → ``None`` (all GPUs)."""
    gd = (gpu_devices or "").strip().lower()
    if not gd or gd == "all":
        return None
    return [int(x.strip()) for x in gd.split(",") if x.strip().isdigit()]


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only — no httpx dependency at calibration time)
# ---------------------------------------------------------------------------


def _http(
    method: str,
    url: str,
    body: dict | None = None,
    timeout_s: float = 30.0,
) -> tuple[int, Any]:
    payload = None
    headers: dict[str, str] = {"User-Agent": "logos-calibrate/1.0"}
    if body is not None:
        payload = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
            parsed: Any = json.loads(raw) if raw else {}
            return resp.status, parsed
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception:
        return 0, {}


def _get(url: str, timeout_s: float = 10.0) -> tuple[int, Any]:
    return _http("GET", url, timeout_s=timeout_s)


def _post(url: str, body: dict | None = None, timeout_s: float = 30.0) -> tuple[int, Any]:
    return _http("POST", url, body=body, timeout_s=timeout_s)


# ---------------------------------------------------------------------------
# vLLM process lifecycle
# ---------------------------------------------------------------------------


def _build_vllm_cmd(
    plan: dict[str, Any],
    vllm_binary: str,
    host: str,
    port: int,
    kv_cache_memory_bytes: str,
) -> list[str]:
    """Build the vLLM command list without spawning a process."""
    model = plan["model"]
    tp = int(plan.get("tensor_parallel_size", 1))
    dtype = str(plan.get("dtype", "auto"))
    quant = str(plan.get("quantization") or "")
    max_model_len = plan.get("max_model_len")
    max_num_seqs = plan.get("max_num_seqs")
    enforce_eager = bool(plan.get("enforce_eager", False))
    disable_custom_all_reduce = bool(plan.get("disable_custom_all_reduce", False))
    # Match the serving lane's engine config. Runtime lanes default to
    # enable_prefix_caching=True (models.LaneConfig), which changes vLLM's KV
    # accounting: the max_model_len that fits a given KV budget WITH prefix
    # caching is a few % lower than without it. Calibrating WITHOUT prefix
    # caching therefore records an optimistic max_model_len that the serving
    # lane can't actually honor (vLLM rejects "needs X GiB > budget" at start).
    # Calibrate the same engine config that serves so the pair curve is exact.
    enable_prefix_caching = bool(plan.get("enable_prefix_caching", True))
    extra_args: list[str] = list(plan.get("extra_args") or [])
    kv_bytes = str(plan.get("kv_cache_memory_bytes") or kv_cache_memory_bytes)
    kv_cache_dtype = str(plan.get("kv_cache_dtype") or "")
    explicit_gmu = plan.get("gpu_memory_utilization")

    cmd = [
        vllm_binary,
        "serve",
        model,
        "--host",
        host,
        "--port",
        str(port),
        "--tensor-parallel-size",
        str(tp),
        "--dtype",
        dtype,
        "--kv-cache-memory-bytes",
        kv_bytes,
        "--enable-sleep-mode",
    ]
    if enable_prefix_caching:
        cmd.append("--enable-prefix-caching")
    if explicit_gmu is not None:
        cmd.extend(["--gpu-memory-utilization", str(explicit_gmu)])
    if max_model_len:
        cmd.extend(["--max-model-len", str(int(max_model_len))])
    if max_num_seqs:
        cmd.extend(["--max-num-seqs", str(int(max_num_seqs))])
    if quant:
        cmd.extend(["--quantization", quant])
    if kv_cache_dtype:
        cmd.extend(["--kv-cache-dtype", kv_cache_dtype])
    if enforce_eager:
        cmd.append("--enforce-eager")
    if disable_custom_all_reduce:
        cmd.append("--disable-custom-all-reduce")
    cmd.extend(extra_args)
    return cmd


def spawn_vllm(
    plan: dict[str, Any],
    vllm_binary: str,
    host: str,
    port: int,
    log_path: Path,
    kv_cache_memory_bytes: str,
    *,
    nccl_p2p_available: bool = False,
    hf_home: str | None = None,
) -> tuple[subprocess.Popen[str], list[str]]:
    """Spawn vLLM and return ``(process, cmd_list)``."""
    tp = int(plan.get("tensor_parallel_size", 1))

    cmd = _build_vllm_cmd(plan, vllm_binary, host, port, kv_cache_memory_bytes)

    env = os.environ.copy()
    env["VLLM_SERVER_DEV_MODE"] = "1"
    # Keep venv tools (ninja etc.) visible even outside activated venv
    vllm_dir = str(Path(vllm_binary).resolve().parent)
    env["PATH"] = f"{vllm_dir}{os.pathsep}{env.get('PATH', '')}"

    # Override HF_HOME to load from tmpfs RAM cache if provided.
    if hf_home:
        env["HF_HOME"] = hf_home
        logger.info("  HF_HOME=%s (tmpfs RAM cache)", hf_home)

    # NCCL P2P: disabled by default (PCIe-only assumed).
    # Set nccl_p2p_available=True for NVLink setups.
    if not nccl_p2p_available:
        env.setdefault("NCCL_P2P_DISABLE", "1")
        logger.info(
            "  NCCL_P2P_DISABLE=1 (PCIe topology — no NVLink; "
            "set engines.vllm.nccl_p2p_available=true in config.yml to enable P2P)"
        )
    else:
        logger.info("  NCCL P2P enabled (NVLink topology)")

    # For tensor-parallel calibration runs (tp > 1), mirror the NCCL env vars
    # used by regular vLLM lanes so calibration matches production behaviour.
    if tp > 1:
        env.setdefault("TORCH_NCCL_ASYNC_ERROR_HANDLING", "1")
        env.setdefault("NCCL_CUMEM_ENABLE", "0")  # unreliable in Docker without NUMA config
        env.setdefault("NCCL_TIMEOUT", "1800")

    gpu_devices = str(plan.get("gpu_devices") or "")
    if gpu_devices and gpu_devices.lower() not in ("all", ""):
        env["CUDA_VISIBLE_DEVICES"] = gpu_devices

    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Append mode — preserves logs from earlier calibration attempts so the
    # full search history is visible in a single file, not just the last probe.
    log_file = log_path.open("a", encoding="utf-8")
    try:
        kv_bytes = str(plan.get("kv_cache_memory_bytes") or kv_cache_memory_bytes)
        _sep = "=" * 72
        log_file.write(
            f"\n{_sep}\n"
            f"  Calibration probe — {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"  KV cache: {kv_bytes}  TP: {tp}\n"
            f"  Command: {' '.join(cmd)}\n"
            f"{_sep}\n\n"
        )
        log_file.flush()
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
    finally:
        log_file.close()

    logger.info("  Spawned PID=%d  log=%s", proc.pid, log_path)
    logger.info("  Command: %s", " ".join(cmd))
    return proc, cmd


def _kill_stale_vllm_workers() -> None:
    """Kill any orphaned ``VLLM::Worker`` or ``vllm`` processes.

    Scans ``/proc`` directly (no psutil dependency) for processes whose
    ``/proc/<pid>/comm`` contains ``vllm`` (case-insensitive) — this
    catches both the ``VLLM::Worker`` subprocesses and lingering ``vllm
    serve`` parents.
    """
    proc_root = Path("/proc")
    if not proc_root.exists():
        return  # not Linux
    killed = 0
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().decode("utf-8", errors="replace")
        except Exception:
            continue
        # Match both "vllm serve ..." parents and "VLLM::Worker" children
        if "vllm" not in cmdline.lower():
            continue
        pid = int(entry.name)
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, signal.SIGKILL)
            killed += 1
        except OSError:
            pass
    if killed:
        logger.info("  Killed %d stale vLLM process(es)", killed)
        time.sleep(_VRAM_SETTLE_S)  # let GPU memory release


def _read_log_tail(log_path: Path, max_lines: int = 80) -> str:
    """Read the last *max_lines* of a vLLM log file, or '' on failure."""
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = lines[-max_lines:] if len(lines) > max_lines else lines
        return "\n".join(tail)
    except Exception:
        return ""


def stop_vllm(proc: subprocess.Popen[str]) -> None:
    """Stop a vLLM process and all its child workers.

    Uses process-group kill (enabled by ``start_new_session=True`` in
    ``spawn_vllm``) so orphaned ``VLLM::Worker`` subprocesses are
    cleaned up even when the parent has already crashed.
    """
    pgid: int | None = None
    try:
        pgid = os.getpgid(proc.pid)
    except OSError:
        pass  # process already gone

    if proc.poll() is None:
        # Parent still running — try graceful shutdown first
        if pgid is not None:
            try:
                os.killpg(pgid, signal.SIGTERM)
            except OSError:
                pass
        else:
            proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=_VLLM_STOP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            pass  # fall through to SIGKILL below

    # Force-kill the entire process group to catch orphaned workers
    if pgid is not None:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except OSError:
            pass  # already gone

    # Reap the main process
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


def wait_ready(
    base_url: str,
    timeout_s: float,
    proc: subprocess.Popen[str],
    gpu_indices: list[int] | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    deadline = time.perf_counter() + timeout_s
    t_start = time.perf_counter()
    last_log = t_start - 25.0  # log at ~5 s, then every 30 s
    while time.perf_counter() < deadline:
        # Honor mid-probe cancellation: the calibration session sets this
        # when the maintenance window closes (or operator calls stop). Bail
        # within ~2s instead of waiting out the full ready_timeout.
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("cancelled")
        if proc.poll() is not None:
            raise RuntimeError(f"vLLM exited before becoming ready (code={proc.poll()})")
        status, _ = _get(f"{base_url}/health", timeout_s=5.0)
        if status == 200:
            return
        now = time.perf_counter()
        if now - last_log >= 30.0:
            elapsed = now - t_start
            vram_str = ""
            try:
                used = _total_used_mb(query_gpu_vram(gpu_indices))
                vram_str = f"  VRAM={used:.0f} MB"
            except Exception:
                pass
            logger.info(
                "        %.0fs — weights loaded, waiting for CUDA graph warmup%s",
                elapsed,
                vram_str,
            )
            last_log = now
        time.sleep(2.0)
    raise TimeoutError(f"vLLM not ready after {timeout_s:.0f}s")


def warmup_inference(base_url: str, model: str, timeout_s: float = 120.0) -> bool:
    """Trigger a single 1-token completion to force lazy GPU allocations.

    Without this, ``/health=200`` only guarantees weights are loaded — CUDA
    graphs are captured lazily on the first real request, FlashInfer kernels
    JIT on first use, and Triton autotunes per-shape. The peak VRAM the
    planner needs to budget for is post-first-request, not post-load.

    Sends one ``/v1/completions`` with ``max_tokens=1``. Returns True on
    success, False on any HTTP error (caller logs and continues — failure
    here doesn't fail calibration, the awake measurement is still useful).
    """
    body = {
        "model": model,
        "prompt": "hi",
        "max_tokens": 1,
        "temperature": 0.0,
        "stream": False,
    }
    status, _ = _post(f"{base_url}/v1/completions", body=body, timeout_s=timeout_s)
    return status == 200


def wait_sleep_state(base_url: str, target: bool, timeout_s: float) -> None:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        status, payload = _get(f"{base_url}/is_sleeping", timeout_s=5.0)
        if status == 200 and isinstance(payload, dict):
            if bool(payload.get("is_sleeping")) is target:
                return
        time.sleep(0.5)
    raise TimeoutError(f"/is_sleeping did not reach {target} within {timeout_s:.0f}s")


# ---------------------------------------------------------------------------
# Calibration logic
# ---------------------------------------------------------------------------


@dataclass
class CalibrationResult:
    model: str
    tensor_parallel_size: int
    gpu_devices: str
    kv_cache_sent_mb: float  # what we explicitly gave vLLM during calibration
    success: bool
    loaded_vram_mb: float = 0.0  # measured: total GPU delta while awake
    sleeping_residual_mb: float = 0.0  # measured: total GPU delta while sleeping
    base_residency_mb: float = 0.0  # = loaded_vram_mb (weights + KV, full footprint)
    # KV cache envelope discovered during calibration on this hardware. ``min``
    # is the smallest kv_cache_memory_bytes value at which the model loaded and
    # responded (the floor probe in Phase 2); ``max`` is the largest the binary
    # search confirmed fits without OOM. The planner picks any value in
    # [min, max] at lane-spawn time depending on how much VRAM is free — when
    # other lanes occupy the GPU it spawns with kv near min so the new lane
    # coexists, when the GPU is empty it can spawn near max for full
    # concurrency throughput. Both default to 0.0 on legacy results, in which
    # case the caller leaves the profile's min/max_kv_cache_mb at None and the
    # planner falls back to the old behaviour of using kv_budget_mb directly.
    min_kv_cache_mb: float = 0.0
    max_kv_cache_mb: float = 0.0
    calibrated_at: float = 0.0
    error: str = ""
    # Records what enforce_eager was used during this calibration. Persisted in
    # the profile so the worker can detect mismatches against production overrides
    # and trigger recalibration when CUDA-graph state would change the footprint.
    enforce_eager: bool = False
    # Peak transient host-RAM consumption measured during the sleep call
    # (one of sleep_l1 / sleep_l2 depending on `sleep_level` for this run).
    # Captured by sampling /proc/meminfo MemAvailable at ~50ms during the
    # /sleep HTTP call. The other slot stays None — the planner falls back
    # to a heuristic when missing.
    sleep_l1_transient_host_ram_mb: float | None = None
    sleep_l2_transient_host_ram_mb: float | None = None
    # Set when calibrate_model bails because the model itself can never
    # load on this worker (bad repo id, gated repo, unsupported architecture).
    # Caller persists the model into model_profiles.yml so the master's
    # orchestrator stops scheduling calibration attempts. Distinct from
    # `success=False` with a generic error — those are still worth retrying
    # next window. ``unsupported_reason`` is the FatalLoadErrorPattern code.
    unsupported_reason: str | None = None
    # Set when calibrate_model bails because the NODE is in a degraded
    # state (filesystem EIO, read-only mount, etc. — see
    # ``_NODE_LEVEL_TRANSIENT_PATTERNS``). Distinct from
    # ``unsupported_reason``: that one marks a single model permanently,
    # this one marks the whole node as broken until ops intervenes.
    # The bridge surfaces this into the runtime status so the master's
    # orchestrator stops sending calibration commands until the node
    # recovers. Critically: when this is set, NO blacklist entry of any
    # kind was written — the failure isn't the calibration's fault and
    # leaving artefacts behind just pollutes things (see deioma 2026-06-04).
    node_unhealthy_reason: str | None = None
    # ``max_model_len`` actually used during the successful probe(s). When
    # vLLM refuses to start because the configured KV budget can't hold one
    # request at the model's default max_seq_len, calibration parses vLLM's
    # own suggestion ("estimated maximum model length is N") and re-probes
    # with --max-model-len=N. Persisting the resolved value here lets the
    # planner pass the same flag at lane spawn — otherwise the lane reverts
    # to the default max_seq_len and refuses to start on the same budget.
    # 0 means "use the model default" (operator either didn't pin a tight
    # kv_cache or the model's default fits).
    max_model_len: int = 0
    # Sweep points collected during calibration, ordered by ascending KV.
    # Each tuple is (kv_cache_mb, max_model_len) and represents one point on
    # the reachable context curve for this model on this hardware.
    kv_max_model_len_pairs: list[tuple[float, int]] | None = None
    # Same sweep points annotated with the achievable concurrency (parallelity
    # factor = kv_cache_tokens / max_model_len) vLLM reported at each KV size.
    # Each tuple is (kv_cache_mb, max_model_len, parallelity). ``parallelity`` is
    # None when neither a probed anchor nor the KV→context rate could supply it.
    # The planner uses it to place lanes with enough KV for >=2 concurrent
    # full-context requests when memory allows.
    kv_max_model_len_parallelity_pairs: list[tuple[float, int, float | None]] | None = None
    # ``max_num_seqs`` actually used during the successful probe(s). Set when
    # calibration auto-injected --max-num-seqs because a hybrid Mamba/SSM
    # model's state-cache pool was smaller than the default 1024. Persisted so
    # the lane spawner passes the same flag; 0 means no cap was needed.
    max_num_seqs: int = 0


def _sample_host_ram_available_mb() -> float | None:
    """Read /proc/meminfo MemAvailable, return MB. None when unavailable."""
    try:
        with open("/proc/meminfo", "rb") as f:
            for line in f:
                if line.startswith(b"MemAvailable:"):
                    parts = line.split()
                    return float(parts[1]) / 1024.0  # kB → MB
    except OSError:
        return None
    return None


@contextmanager
def _track_host_ram_transient(
    interval_s: float = 0.05,
) -> Iterator[dict[str, float | None]]:
    """Sample MemAvailable while inside this block; report peak transient delta.

    Yields a dict that will hold ``baseline_mb`` and ``transient_mb`` (peak
    consumption = baseline_mb − min_available_during_block) once the block
    exits. Both fields are None when /proc/meminfo is unavailable.
    """
    result: dict[str, float | None] = {"baseline_mb": None, "transient_mb": None}
    baseline = _sample_host_ram_available_mb()
    if baseline is None:
        yield result
        return

    result["baseline_mb"] = baseline
    stop = threading.Event()
    min_seen = baseline

    def _poll() -> None:
        nonlocal min_seen
        while not stop.wait(interval_s):
            sample = _sample_host_ram_available_mb()
            if sample is not None and sample < min_seen:
                min_seen = sample

    thread = threading.Thread(target=_poll, daemon=True)
    thread.start()
    try:
        yield result
    finally:
        stop.set()
        thread.join(timeout=2.0)
        # Final snapshot in case the operation completed before the poller fired
        final_sample = _sample_host_ram_available_mb()
        if final_sample is not None and final_sample < min_seen:
            min_seen = final_sample
        result["transient_mb"] = max(baseline - min_seen, 0.0)


def calibrate_model(
    plan: dict[str, Any],
    *,
    vllm_binary: str,
    port: int,
    log_dir: Path,
    sleep_level: int,
    ready_timeout_s: float,
    nccl_p2p_available: bool = False,
    hf_home: str | None = None,
    model_cache: Any | None = None,
    cancel_event: threading.Event | None = None,
) -> CalibrationResult:
    # Honor the production enforce_eager setting (default False, matching the
    # worker schema). Calibrating in a different mode than production runs
    # produces systematically wrong loaded_vram_mb / sleeping_residual_mb
    # because CUDA graph capture pools and workspace stay resident across
    # sleep_l1 — so the planner under-counts VRAM and OOMs at wake/load time.
    eager_mode = bool(plan.get("enforce_eager", False))
    if eager_mode:
        logger.info("  enforce_eager=True — CUDA graph capture skipped (~minutes faster, no graph state retained)")
    else:
        logger.info(
            "  enforce_eager=False — graphs will be captured; loaded/sleeping VRAM include capture-pool overhead"
        )
    plan = {**plan, "enforce_eager": eager_mode}

    model = plan["model"]
    gpu_devices = str(plan.get("gpu_devices") or "")
    tp = int(plan.get("tensor_parallel_size", 1))
    gpu_indices = parse_gpu_indices(gpu_devices)
    host = "127.0.0.1"
    base_url = f"http://{host}:{port}"
    log_path = log_dir / f"{model.replace('/', '__')}.log"

    partial = CalibrationResult(
        model=model,
        tensor_parallel_size=tp,
        gpu_devices=gpu_devices,
        kv_cache_sent_mb=0.0,
        success=False,
    )

    logger.info("-" * 60)
    logger.info("Calibrating: %s", model)
    logger.info(
        "  tp=%d  gpu_devices=%s  sleep_level=%d",
        tp,
        gpu_devices or "all",
        sleep_level,
    )
    logger.info("-" * 60)

    # Phase 0a — Model-level "do not retry" check. A previous calibration
    # attempt classified this model as permanently unsupported on this
    # worker (bad repo id, gated repo, missing architecture). Kv-cache
    # probing cannot fix any of those, so short-circuit before spawning
    # vLLM. Operators clear the entry by editing the file.
    unsupported_path = log_dir / _UNSUPPORTED_MODELS_FILE
    _unsupported = _load_unsupported_models(unsupported_path).get(model)
    if _unsupported is not None:
        partial.error = (
            f"model is on the unsupported list "
            f"(reason={_unsupported.reason_code}, recorded_at={_unsupported.recorded_at}): "
            f"{_unsupported.description}"
        )
        partial.unsupported_reason = _unsupported.reason_code
        logger.warning(
            "  SKIP: %s. To re-attempt after fixing the underlying issue, " "remove the line from %s.",
            partial.error,
            unsupported_path,
        )
        return partial

    # Phase 0 — Kill any orphaned vLLM workers from previous runs.
    # Without this, leaked GPU memory inflates the baseline and can cause
    # subsequent calibrations to OOM or hang.
    _kill_stale_vllm_workers()

    if cancel_event is not None and cancel_event.is_set():
        partial.error = "cancelled"
        return partial

    # Phase 1 — Baseline: measure before any model process exists.
    # Retry up to 3 times with a short delay — nvidia-smi can be temporarily
    # sluggish right after a previous heavy calibration run (GPU driver busy).
    logger.info("  [1/5] Baseline VRAM...")
    baseline_mb: float | None = None
    for _attempt in range(3):
        try:
            baseline_mb = sample_vram_mb(gpu_indices)
            break
        except Exception as exc:
            last_exc = exc
            if _attempt < 2:
                logger.warning(
                    "  nvidia-smi baseline attempt %d failed: %s — retrying in 15s",
                    _attempt + 1,
                    exc,
                )
                time.sleep(15)
    if baseline_mb is None:
        partial.error = f"nvidia-smi baseline failed: {last_exc}"
        logger.warning("  ERROR: %s", partial.error)
        return partial
    logger.info("        baseline = %.0f MB", baseline_mb)

    if cancel_event is not None and cancel_event.is_set():
        partial.error = "cancelled"
        return partial

    # Compute VRAM cap for KV cache search.
    # Use per-GPU VRAM × tp so the cap reflects the GPUs actually used,
    # not all GPUs visible on the host.
    max_kv_mb = float("inf")
    try:
        gpu_snap = query_gpu_vram(gpu_indices)
        per_gpu_mb = min(v["total_mb"] for v in gpu_snap.values())
        effective_gpu_mb = per_gpu_mb * tp
        max_kv_mb = per_gpu_mb * _KV_CACHE_VRAM_CAP_RATIO
        logger.info(
            "  GPU VRAM = %.0f MB/GPU × tp=%d = %.0f MB effective, " "KV cache search cap (%.0f%%) = %.0f MB",
            per_gpu_mb,
            tp,
            effective_gpu_mb,
            _KV_CACHE_VRAM_CAP_RATIO * 100,
            max_kv_mb,
        )
    except Exception as exc:
        logger.warning(
            "  Could not query GPU VRAM for KV cache cap: %s — no cap applied",
            exc,
        )

    # Phase 2 — Sweep KV cache sizes and derive the reachable max_model_len
    # curve on this hardware.
    #
    # For each KV step we start from the model default (no forced
    # --max-model-len) and only inject vLLM's own suggestion when needed,
    # so larger-KV probes never inherit a lowered max_model_len from smaller
    # steps.
    #
    # A per-model override (plan["kv_cache_memory_bytes"]) still skips the
    # sweep and uses a fixed KV value.
    explicit_kv = plan.get("kv_cache_memory_bytes")
    if explicit_kv:
        # Per-model override — use as-is, no search.  Both min and max
        # collapse to the operator-pinned value so the runtime clamp in
        # the planner is a no-op (it'll always pick this value).
        kv_cache_sent_mb = _parse_kv_to_mb(str(explicit_kv))
        kv_search = False
        min_kv_observed_mb = kv_cache_sent_mb
        max_kv_observed_mb = kv_cache_sent_mb
        logger.info(
            "  [2/6] Using explicit kv_cache=%s (%.0f MB) — no search",
            explicit_kv,
            kv_cache_sent_mb,
        )
    else:
        kv_search = True
        kv_cache_sent_mb = max_kv_mb if max_kv_mb < float("inf") else 4096.0
        # Round down to whole GB
        kv_cache_sent_mb = math.floor(kv_cache_sent_mb / 1024.0) * 1024.0
        # Min/max get filled in below once the search confirms the floor
        # actually loads.  Left at 0.0 here so a search abort doesn't
        # masquerade as a valid envelope on the result.
        min_kv_observed_mb = 0.0
        max_kv_observed_mb = 0.0
        logger.info(
            "  [2/6] Searching max KV cache (floor=%.0f MB, " "ceiling=%.0f MB, step=%.0f MB)...",
            _KV_CACHE_MIN_STEP_MB,
            kv_cache_sent_mb,
            _KV_CACHE_MIN_STEP_MB,
        )

    failed_path = log_dir / _FAILED_COMMANDS_FILE
    succeeded_path = log_dir / _SUCCEEDED_COMMANDS_FILE
    failed_commands = _load_failed_commands(failed_path)
    succeeded_commands = _load_succeeded_commands(succeeded_path)

    # Lazy RAM-cache flag: only cache the model into tmpfs on the first
    # actual vLLM spawn (not on blacklist-skipped probes).
    _ram_cached = hf_home is not None  # already cached if hf_home was passed

    # Sentinel returned by _try_start when a whitelisted probe is skipped
    # (trusted success without spawning).  Callers check ``is _WHITELIST_HIT``
    # to distinguish from a real running process.
    _WHITELIST_HIT = object()

    # Probe-result map keyed by kv_mb. Used by _try_start (blacklist skip) and,
    # in search mode, also by _record_probe / _render_search_bar. Initialise
    # unconditionally so the closure cell exists even when an explicit
    # kv_cache_memory_bytes override skips the search branch — otherwise the
    # blacklist-skip write inside _try_start raises NameError.
    _probes: dict[float, str] = {}

    # Single-element box (mutable across closure scope without `nonlocal`)
    # that latches the FatalLoadErrorPattern detected for this model, if
    # any. Once set, subsequent _try_start calls short-circuit so the
    # kv-cache search doesn't spawn vLLM N more times to watch each kv
    # produce the same identity-level error.
    _unsupported_box: list[FatalLoadErrorPattern] = []

    # Sibling latch for node-level transient failures (filesystem EIO,
    # read-only mount, …). When set, the kv-cache search aborts without
    # writing ANY blacklist artefact — neither the per-command file nor
    # the per-model unsupported list. The bridge reads the latch via
    # ``partial.node_unhealthy_reason`` and surfaces it into the runtime
    # status so the master skips this worker until ops intervenes.
    _node_unhealthy_box: list[NodeTransientErrorPattern] = []

    # Cap on per-probe ``--max-model-len`` shrink-and-retry attempts. We keep
    # this local to one probe so each KV step starts from the model default
    # and derives max_model_len fresh (no cross-step mutation leak).
    _MAX_MODEL_LEN_RETRIES_PER_KV = 3

    # Cap on per-probe ``--max-num-seqs`` shrink-and-retry attempts for hybrid
    # Mamba/SSM models. vLLM reports the exact ceiling ("at most N"), so a
    # single inject-and-retry normally converges; a second attempt covers the
    # case where the first shrink still leaves max_num_seqs above the pool
    # after a kv change. More than that signals a different problem.
    _MAX_NUM_SEQS_RETRIES_PER_KV = 2
    resolved_max_num_seqs = int(plan.get("max_num_seqs") or 0)

    def _override_error_if_unsupported() -> None:
        """If a fatal model-level error was detected mid-search, replace
        the partial's generic "no working kv" message with the specific
        reason code so the bridge / orchestrator can persist the model
        into the unsupported-models registry. Node-level transient
        failures (filesystem EIO, …) win over model-level fatalities
        because they invalidate every measurement on this run.
        """
        if _node_unhealthy_box:
            pat = _node_unhealthy_box[0]
            partial.node_unhealthy_reason = pat.reason_code
            partial.error = f"node degraded ({pat.reason_code}): {pat.description}"
            return
        if not _unsupported_box:
            return
        pat = _unsupported_box[0]
        partial.unsupported_reason = pat.reason_code
        partial.error = f"unsupported model ({pat.reason_code}): {pat.description}"

    def _try_start(
        kv_mb: float,
        *,
        plan_overrides: dict[str, Any] | None = None,
        record_blacklist: bool = True,
        allow_whitelist: bool = True,
    ) -> subprocess.Popen[str] | object | None:
        """Try to start vLLM with the given KV cache.

        Returns:
          - A running ``Popen`` on real success.
          - ``_WHITELIST_HIT`` sentinel if the command is whitelisted
            (known-good from a previous run) — no process spawned.
          - ``None`` on failure, blacklist skip, or when an earlier probe
            in this calibration already detected a permanent
            model-identity-level failure (see ``_unsupported_box``) or a
            node-level transient failure (see ``_node_unhealthy_box``).
        """
        nonlocal hf_home, _ram_cached
        # Short-circuit: a prior probe already proved this model can't load,
        # or proved the node itself is degraded.
        if _unsupported_box or _node_unhealthy_box:
            return None
        kv_str = _format_kv_mb(kv_mb)
        planned = {**plan, "kv_cache_memory_bytes": kv_str}
        if plan_overrides:
            planned.update(plan_overrides)
        fingerprint = _cmd_fingerprint(_build_vllm_cmd(planned, vllm_binary, host, port, kv_str))
        # Whitelist: known-good from a previous calibration run.  Trust the
        # result — skip the expensive vLLM spawn during the binary search.
        if allow_whitelist and fingerprint in succeeded_commands:
            if fingerprint in failed_commands:
                # Also blacklisted (e.g. stuck-GPU session added it later).
                # Whitelist wins — clean up the stale blacklist entry.
                _remove_failed_command(failed_path, fingerprint)
                failed_commands.discard(fingerprint)
            logger.info("        OK kv_cache=%s (whitelisted, skipping spawn)", kv_str)
            return _WHITELIST_HIT
        # Blacklist: known-bad, skip.
        if record_blacklist and fingerprint in failed_commands:
            logger.warning(
                "        SKIP kv_cache=%s — blacklisted",
                kv_str,
            )
            _probes[kv_mb] = "skip"
            return None
        # Lazy RAM cache: copy model into tmpfs on first real spawn.
        if not _ram_cached and model_cache is not None:
            logger.info("  [RAM cache] Caching %s into tmpfs before first probe...", model)
            _hf = model_cache.ensure_cached_sync(model) or None
            if _hf:
                is_tmpfs = hasattr(model_cache, "_cache_hub") and _hf == str(model_cache._cache_hub.parent)
                if is_tmpfs:
                    hf_home = _hf
                    logger.info("  [RAM cache] %s → loading from tmpfs", model)
                else:
                    logger.info("  [RAM cache] %s → loading from disk (tmpfs full)", model)
            _ram_cached = True
        proc, _ = spawn_vllm(
            planned,
            vllm_binary,
            host,
            port,
            log_path,
            kv_cache_memory_bytes=kv_str,
            nccl_p2p_available=nccl_p2p_available,
            hf_home=hf_home,
        )
        logger.info(
            "        Trying kv_cache=%s (%.0f MB, timeout=%.0fs)...",
            kv_str,
            kv_mb,
            ready_timeout_s,
        )
        t0 = time.perf_counter()
        try:
            wait_ready(base_url, ready_timeout_s, proc, gpu_indices, cancel_event=cancel_event)
            logger.info(
                "        OK kv_cache=%s ready in %.1fs",
                kv_str,
                time.perf_counter() - t0,
            )
            if plan_overrides is not None:
                plan_overrides["_resolved_max_model_len"] = int(planned.get("max_model_len") or 0)
                plan_overrides["_resolved_max_num_seqs"] = int(planned.get("max_num_seqs") or 0)
            # Record success — whitelist this command for future runs.
            _record_succeeded_command(succeeded_path, fingerprint)
            succeeded_commands.add(fingerprint)
            # Remove from blacklist if it was there (stale entry from e.g.
            # a previous stuck-GPU session).
            if fingerprint in failed_commands:
                _remove_failed_command(failed_path, fingerprint)
                failed_commands.discard(fingerprint)
                logger.info("        Removed stale blacklist entry for kv_cache=%s", kv_str)
            return proc
        except (RuntimeError, TimeoutError) as exc:
            # Cancellation path: kill the probe immediately, do not blacklist.
            # The session-level driver sees cancel_event and bails after this
            # returns None, so we just need to stop vLLM and leave no trace.
            if str(exc) == "cancelled":
                logger.info(
                    "        Calibration cancelled mid-probe kv_cache=%s — stopping vLLM",
                    kv_str,
                )
                stop_vllm(proc)
                time.sleep(_VRAM_SETTLE_S)
                return None
            log_tail = _read_log_tail(log_path)
            logger.warning(
                "        FAIL kv_cache=%s: %s",
                kv_str,
                exc,
            )
            if log_tail:
                logger.warning(
                    "  -- vLLM log tail --\n%s%s%s\n  -- end vLLM log tail --",
                    _C_DIM,
                    log_tail,
                    _C_RESET,
                )
            stop_vllm(proc)
            time.sleep(_VRAM_SETTLE_S)

            # Check node-level transient failures FIRST — these (filesystem
            # EIO, read-only mount, …) are not the calibration's fault and
            # must NOT leave any artefact behind. If we recorded per-command
            # blacklist lines for them we'd accumulate dozens of garbage
            # entries during a single 10-minute Ceph outage (see deioma
            # 2026-06-04). Latch the box, log loudly, and abort. The bridge
            # reads the partial result, surfaces ``node_unhealthy_reason``
            # into the runtime status, and the master orchestrator skips
            # this worker until the node recovers.
            node_pattern = _classify_node_transient_error(log_tail)
            if node_pattern is not None:
                if not _node_unhealthy_box:
                    _node_unhealthy_box.append(node_pattern)
                    logger.error(
                        "  %sNODE DEGRADED%s — %s: %s. "
                        "Aborting calibration on %s — NO blacklist entries "
                        "written. Operator action required.",
                        _C_BOLD + _C_RED,
                        _C_RESET,
                        node_pattern.reason_code,
                        node_pattern.description,
                        model,
                    )
                return None

            # KV-too-small-for-default-max-seq-len recovery. vLLM refuses to
            # start at all when the configured KV budget can't fit even one
            # request at the model's default max_seq_len (e.g. Llama-3.1-8B's
            # 131072 needs ~8 GiB; operator pinned kv_cache=6G). Instead of
            # blacklisting the command and failing the model, parse vLLM's
            # own suggestion from the log tail and re-probe the same kv_mb
            # with --max-model-len injected. The new fingerprint differs
            # (carries --max-model-len) so the blacklist check sees it as a
            # fresh attempt.
            suggested_max_len = _extract_vllm_max_model_len_suggestion(log_tail)
            if suggested_max_len is not None:
                attempts_used = int(planned.get("_max_model_len_retry_count") or 0)
                current_max = planned.get("max_model_len")
                current_max_int = int(current_max) if current_max else None
                shrinks = current_max_int is None or suggested_max_len < current_max_int
                if shrinks and attempts_used < _MAX_MODEL_LEN_RETRIES_PER_KV:
                    logger.warning(
                        "        vLLM rejected kv_cache=%s for max_seq_len; "
                        "injecting --max-model-len=%d (was %s) and retrying "
                        "(attempt %d/%d)",
                        kv_str,
                        suggested_max_len,
                        current_max_int if current_max_int is not None else "unset",
                        attempts_used + 1,
                        _MAX_MODEL_LEN_RETRIES_PER_KV,
                    )
                    if plan_overrides is None:
                        plan_overrides = {}
                    retry_overrides = plan_overrides
                    retry_overrides["max_model_len"] = suggested_max_len
                    retry_overrides["_max_model_len_retry_count"] = attempts_used + 1
                    return _try_start(
                        kv_mb,
                        plan_overrides=retry_overrides,
                        record_blacklist=record_blacklist,
                        allow_whitelist=allow_whitelist,
                    )

            # Hybrid Mamba/SSM state-cache recovery. vLLM aborts CUDA-graph
            # capture when max_num_seqs (default 1024) exceeds the model's
            # fixed Mamba cache-block pool. It names the exact ceiling, so
            # re-probe the same kv_mb with --max-num-seqs injected instead of
            # blacklisting the command. The resolved value is captured from the
            # successful probe and persisted so the lane spawner can reuse it —
            # otherwise the lane reverts to 1024 and crashes identically at runtime.
            suggested_max_seqs = _extract_vllm_max_num_seqs_suggestion(log_tail)
            if suggested_max_seqs is not None:
                ns_attempts_used = int(planned.get("_max_num_seqs_retry_count") or 0)
                current_seqs = planned.get("max_num_seqs")
                current_seqs_int = int(current_seqs) if current_seqs else None
                ns_shrinks = current_seqs_int is None or suggested_max_seqs < current_seqs_int
                if ns_shrinks and ns_attempts_used < _MAX_NUM_SEQS_RETRIES_PER_KV:
                    logger.warning(
                        "        vLLM rejected kv_cache=%s: max_num_seqs exceeds "
                        "Mamba cache blocks; injecting --max-num-seqs=%d (was %s) "
                        "and retrying (attempt %d/%d)",
                        kv_str,
                        suggested_max_seqs,
                        current_seqs_int if current_seqs_int is not None else "unset",
                        ns_attempts_used + 1,
                        _MAX_NUM_SEQS_RETRIES_PER_KV,
                    )
                    if plan_overrides is None:
                        plan_overrides = {}
                    retry_overrides = plan_overrides
                    retry_overrides["max_num_seqs"] = suggested_max_seqs
                    retry_overrides["_max_num_seqs_retry_count"] = ns_attempts_used + 1
                    return _try_start(
                        kv_mb,
                        plan_overrides=retry_overrides,
                        record_blacklist=record_blacklist,
                        allow_whitelist=allow_whitelist,
                    )

            # Normal recoverable failure (OOM at this kv, NCCL timeout, …):
            # record the per-command blacklist line so the kv search avoids
            # re-trying this exact fingerprint on the next pass.
            if record_blacklist:
                _record_failed_command(failed_path, fingerprint)
                failed_commands.add(fingerprint)
            # Remove stale whitelist entry — this command no longer works.
            succeeded_commands.discard(fingerprint)

            # Look for fatal, model-identity-level errors in the log tail
            # (bad repo id, gated repo, unsupported architecture, …). When
            # one matches, no other kv-cache size will help — every probe
            # will produce an identical log tail and a fresh blacklist
            # line. Persist into the model-level unsupported list and
            # latch ``_unsupported_box`` so the search loops bail without
            # spawning vLLM again.
            fatal_pattern = _classify_fatal_load_error(log_tail)
            if fatal_pattern is not None and not _unsupported_box:
                _record_unsupported_model(
                    unsupported_path,
                    UnsupportedModelEntry(
                        model=model,
                        reason_code=fatal_pattern.reason_code,
                        recorded_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        description=fatal_pattern.description,
                    ),
                )
                logger.warning(
                    "  %s detected — aborting kv-cache search for model %s.",
                    fatal_pattern.reason_code,
                    model,
                )
                _unsupported_box.append(fatal_pattern)
            return None

    proc: subprocess.Popen[str] | None = None

    if kv_search:
        search_lo = _KV_CACHE_MIN_STEP_MB  # 1 GB floor
        search_hi = kv_cache_sent_mb  # ceiling (80% of per-GPU VRAM)
        original_ceiling = search_hi

        def _stop_if_real(result: object) -> None:
            """Stop the vLLM process unless it's a whitelist sentinel."""
            if result is not _WHITELIST_HIT and result is not None:
                stop_vllm(result)  # type: ignore[arg-type]
                time.sleep(_VRAM_SETTLE_S)

        logger.info(
            "  Legend: %s✓%s=ok  %s✗%s=fail  %s─%s=blacklisted  " "%s✓%s=whitelisted  %s·%s=untested",
            _C_GREEN,
            _C_RESET,
            _C_RED,
            _C_RESET,
            _C_YELLOW,
            _C_RESET,
            _C_CYAN,
            _C_RESET,
            _C_DIM,
            _C_RESET,
        )

        # ── Probe one KV size with a FRESH max_model_len ─────────────────────
        # Never inherit a shrunk max_model_len from a smaller-KV probe. Returns
        # the resolved max_model_len on success, or None if the model failed to
        # start at this KV size. Records the probe in _probes and renders the bar.
        model_default_max_len: int | None = None
        kv_needed_for_full_mb: float | None = None
        best_kv: float | None = None
        # Achievable concurrency (parallelity factor) vLLM reported at each KV
        # probe, keyed by kv_mb. Read back from the load log rather than pinning
        # --max-num-seqs. Used to annotate the kv→max_model_len curve.
        anchors_parallelity: dict[float, float] = {}

        def _probe_kv(kv_mb: float) -> int | None:
            nonlocal model_default_max_len, kv_needed_for_full_mb, best_kv, resolved_max_num_seqs
            probe_overrides: dict[str, Any] = {"max_model_len": None, "_max_model_len_retry_count": 0}
            p = _try_start(kv_mb, plan_overrides=probe_overrides, record_blacklist=False, allow_whitelist=False)
            if p is None:
                if kv_mb not in _probes:
                    _probes[kv_mb] = "fail"
                logger.info(
                    _render_search_bar(_KV_CACHE_MIN_STEP_MB, original_ceiling, _KV_CACHE_MIN_STEP_MB, _probes, best_kv)
                )
                return None
            _probes[kv_mb] = "ok"
            log_tail = _read_log_tail(log_path)
            _conc = _extract_vllm_max_concurrency(log_tail)
            if _conc is not None:
                anchors_parallelity[kv_mb] = _conc
            suggested_mml = _extract_vllm_max_model_len_suggestion(log_tail)
            if model_default_max_len is None:
                model_default_max_len = _extract_vllm_max_seq_len(log_tail)
            if kv_needed_for_full_mb is None:
                _gib = _extract_vllm_kv_gib_needed_for_full(log_tail)
                if _gib:
                    kv_needed_for_full_mb = _gib * 1024.0
            resolved_mml = int(probe_overrides.get("_resolved_max_model_len") or 0)
            if resolved_mml <= 0:
                resolved_mml = int(suggested_mml or model_default_max_len or 0)
            if resolved_mml <= 0:
                resolved_mml = int(plan.get("max_model_len") or 0)
            resolved_seqs = int(probe_overrides.get("_resolved_max_num_seqs") or 0)
            if resolved_seqs > 0:
                resolved_max_num_seqs = (
                    resolved_seqs if resolved_max_num_seqs <= 0 else min(resolved_max_num_seqs, resolved_seqs)
                )
            _stop_if_real(p)
            logger.info(
                _render_search_bar(_KV_CACHE_MIN_STEP_MB, original_ceiling, _KV_CACHE_MIN_STEP_MB, _probes, kv_mb)
            )
            return resolved_mml

        def _cancelled() -> bool:
            if cancel_event is not None and cancel_event.is_set():
                logger.info("  Calibration cancelled during KV sweep.")
                partial.error = "cancelled"
                return True
            return False

        kv_max_model_len_pairs: list[tuple[float, int]] = []

        # 1) Find the lower edge of the startable window. The floor (1G) usually
        #    works, but a too-small KV can't hold even one request (vLLM refuses
        #    regardless of max_model_len), so scan upward to the smallest KV that
        #    actually loads. None working anywhere ⇒ weights exceed VRAM.
        kv_lo: float | None = None
        first_mml = 0
        kv = search_lo
        while kv <= search_hi:
            if _cancelled():
                return partial
            mml = _probe_kv(kv)
            if mml is not None:
                kv_lo = kv
                first_mml = mml
                break
            kv += _KV_CACHE_MIN_STEP_MB
        if kv_lo is None:
            partial.error = (
                f"No working KV cache size found between {_format_kv_mb(search_lo)} and "
                f"{_format_kv_mb(original_ceiling)} on tp={tp}. Model weights likely exceed available GPU VRAM."
            )
            _override_error_if_unsupported()
            logger.warning("  ERROR: %s", partial.error)
            return partial
        best_kv = kv_lo
        kv_max_model_len_pairs.append((kv_lo, first_mml))
        max_mml_seen = first_mml

        # 2) Determine the curve WITHOUT crawling 1 GiB at a time. vLLM's "KV too
        #    small" error reports both the model's full context (M) and the KV
        #    needed to serve it, i.e. the KV→context rate. So: binary-search the
        #    startable-window ceiling (recording real anchor points), then COMPUTE
        #    max_model_len at every KV step from that rate (capped at M), validated
        #    against the anchors. If the rate is unavailable or fails validation,
        #    fall back to the (sparse but correct) probed anchors.
        plateau_at_floor = bool(model_default_max_len and first_mml >= model_default_max_len)

        # Real anchor points (kv -> actual max_model_len), starting at the floor.
        anchors: dict[float, int] = {kv_lo: first_mml}

        # Binary-search the largest startable KV (loadability is monotonic above
        # kv_lo) — ~log2(window) probes instead of a 1 GiB-per-step walk.
        if search_hi - kv_lo >= _KV_CACHE_MIN_STEP_MB:
            lo, hi = kv_lo, search_hi
            while hi - lo >= _KV_CACHE_MIN_STEP_MB:
                if _cancelled():
                    return partial
                mid = _round_up_gb((lo + hi) / 2.0)
                if mid <= lo:
                    break
                m = _probe_kv(mid)
                if m is None:
                    hi = mid - _KV_CACHE_MIN_STEP_MB
                else:
                    best_kv = mid
                    anchors[mid] = m
                    max_mml_seen = max(max_mml_seen, m)
                    lo = mid
        kv_max = best_kv

        cap = model_default_max_len or max_mml_seen or first_mml

        # Derive the KV→context rate from vLLM's report and validate it against
        # every real anchor; discard it (anchors-only) if it is >10% off anywhere.
        per_token_bytes: float | None = None
        if kv_needed_for_full_mb and model_default_max_len:
            per_token_bytes = (kv_needed_for_full_mb * 1024.0 * 1024.0) / model_default_max_len
            for a_kv, a_mml in anchors.items():
                if a_mml <= 0:
                    continue
                comp = min(cap, int((a_kv * 1024.0 * 1024.0) / per_token_bytes))
                if abs(comp - a_mml) / a_mml > 0.10:
                    logger.warning(
                        "  KV/context rate off at %s (computed=%d vs actual=%d) — using probed anchors only.",
                        _format_kv_mb(a_kv),
                        comp,
                        a_mml,
                    )
                    per_token_bytes = None
                    break

        # Emit the full curve across [kv_lo, kv_max]: real anchors win; gaps are
        # filled from the validated rate (rising + plateau, capped at M), or from
        # the plateau value when the full context already fit at the floor.
        kv_step = kv_lo
        while kv_step <= kv_max:
            if kv_step in anchors:
                mml_pt = anchors[kv_step]
            elif per_token_bytes:
                mml_pt = min(cap, int((kv_step * 1024.0 * 1024.0) / per_token_bytes))
            elif plateau_at_floor:
                mml_pt = cap
            else:
                kv_step += _KV_CACHE_MIN_STEP_MB
                continue  # no signal for this gap — rely on the anchors
            if mml_pt > 0:
                kv_max_model_len_pairs.append((kv_step, mml_pt))
                max_mml_seen = max(max_mml_seen, mml_pt)
            kv_step += _KV_CACHE_MIN_STEP_MB

        # Backfill the plateau and drop non-positive points. Once the curve
        # reaches the model's full context, every LARGER KV still serves at
        # least that context — leaving those upper steps at 0 (or absent) wrongly
        # documents a big-KV lane as max_model_len=0. Hold the plateau (highest
        # mml seen, capped at the model max) across [first-full-context-KV,
        # kv_max], and discard any 0/garbage entries.
        _clean = [(k, m) for k, m in kv_max_model_len_pairs if m and m > 0]
        if _clean:
            _plateau = max(m for _, m in _clean)
            if model_default_max_len:
                _plateau = min(_plateau, int(model_default_max_len))
            _by_kv: dict[float, int] = {}
            for k, m in _clean:
                rk = round(k, 1)
                _by_kv[rk] = max(_by_kv.get(rk, 0), int(m))
            _first_full_kv = min((k for k, m in _clean if m >= _plateau), default=None)
            if _first_full_kv is not None:
                _s = _first_full_kv
                while _s <= kv_max:
                    rk = round(_s, 1)
                    _by_kv[rk] = max(_by_kv.get(rk, 0), _plateau)
                    _s += _KV_CACHE_MIN_STEP_MB
            kv_max_model_len_pairs = sorted(_by_kv.items())

        kv_cache_sent_mb = best_kv
        # Keep the FULL window (rising edge + filled plateau), deduped on exact
        # (kv, max_model_len) and ordered by ascending KV. The planner picks the
        # smallest KV per affordable max_model_len at runtime, so the residual
        # plateau points are harmless and document the whole startable window.
        _deduped: list[tuple[float, int]] = []
        _seen: set[tuple[float, int]] = set()
        for kv_mb, mml in sorted(kv_max_model_len_pairs):
            key = (round(kv_mb, 1), int(mml))
            if key in _seen:
                continue
            _seen.add(key)
            _deduped.append((kv_mb, int(mml)))
        kv_max_model_len_pairs = _deduped
        min_kv_observed_mb = min((kv for kv, _ in kv_max_model_len_pairs), default=best_kv)
        max_kv_observed_mb = kv_max

        partial.kv_max_model_len_pairs = kv_max_model_len_pairs
        if kv_max_model_len_pairs:
            partial.max_model_len = max(mml for _, mml in kv_max_model_len_pairs)
            # Annotate every KV point with its achievable concurrency (parallelity
            # factor = kv_cache_tokens / max_model_len). Prefer the value vLLM
            # reported at a probed anchor; otherwise derive it from the calibrated
            # KV→context rate (per_token_bytes). None when neither is available.
            _anchor_par = {round(k, 1): v for k, v in anchors_parallelity.items()}
            _triples: list[tuple[float, int, float | None]] = []
            for kv_mb, mml in kv_max_model_len_pairs:
                par = _anchor_par.get(round(kv_mb, 1))
                if par is None and per_token_bytes and mml > 0:
                    kv_tokens = (kv_mb * 1024.0 * 1024.0) / per_token_bytes
                    par = kv_tokens / float(mml)
                _triples.append((kv_mb, int(mml), (round(float(par), 3) if par and par > 0 else None)))
            partial.kv_max_model_len_parallelity_pairs = _triples

        logger.info(
            "  KV sweep result: %s%sbest_working=%s%s (step=%.0f MB)",
            _C_BOLD,
            _C_GREEN,
            _format_kv_mb(best_kv),
            _C_RESET,
            _KV_CACHE_MIN_STEP_MB,
        )

        # Start vLLM at the final KV size for VRAM measurement.
        # Must be a real process (not whitelist hit) so we can measure VRAM.
        # Temporarily suppress whitelist so _try_start spawns for real.
        _saved_succeeded = set(succeeded_commands)
        succeeded_commands.clear()
        _final_kv = kv_cache_sent_mb
        for _attempt in range(_FINAL_MEASUREMENT_RETRIES):
            _final_kv_str = _format_kv_mb(_final_kv)
            _final_planned = {**plan, "kv_cache_memory_bytes": _final_kv_str}
            _final_fp = _cmd_fingerprint(_build_vllm_cmd(_final_planned, vllm_binary, host, port, _final_kv_str))
            failed_commands.discard(_final_fp)
            proc = _try_start(_final_kv, record_blacklist=False, allow_whitelist=False)
            if proc is not None:
                kv_cache_sent_mb = _final_kv
                break
            logger.warning(
                "        Final measurement attempt %d/%d at %s failed — %s",
                _attempt + 1,
                _FINAL_MEASUREMENT_RETRIES,
                _format_kv_mb(_final_kv),
                "stepping down" if _final_kv > _KV_CACHE_MIN_STEP_MB else "giving up",
            )
            _final_kv -= _KV_CACHE_MIN_STEP_MB
            if _final_kv < _KV_CACHE_MIN_STEP_MB:
                break

        succeeded_commands.update(_saved_succeeded)

        if proc is None:
            partial.error = (
                f"Model failed to start for final measurement "
                f"(tried down to {_format_kv_mb(_final_kv + _KV_CACHE_MIN_STEP_MB)}) "
                f"on tp={tp}"
            )
            _override_error_if_unsupported()
            logger.warning("  ERROR: %s", partial.error)
            return partial
    else:
        # Fixed KV cache — single attempt (need real process for measurement).
        # Suppress the whitelist (a sentinel hit gives us no process to
        # measure) AND any stale blacklist line for this fingerprint: the
        # operator-pinned value has no search fallback, so a blacklist skip
        # converts a maybe-recoverable case into certain failure, and it
        # short-circuits before the --max-model-len injection retry ever
        # sees a vLLM log to parse (deipapa 2026-06-10: Llama-3.1-8B stayed
        # uncalibratable behind a kv=6G line recorded before the injection
        # existed).
        succeeded_commands.clear()
        _fixed_kv_str = _format_kv_mb(kv_cache_sent_mb)
        _fixed_planned = {**plan, "kv_cache_memory_bytes": _fixed_kv_str}
        _fixed_fp = _cmd_fingerprint(_build_vllm_cmd(_fixed_planned, vllm_binary, host, port, _fixed_kv_str))
        if _fixed_fp in failed_commands:
            failed_commands.discard(_fixed_fp)
            logger.info(
                "        Ignoring stale blacklist entry for operator-pinned kv_cache=%s",
                _fixed_kv_str,
            )
        explicit_probe_overrides: dict[str, Any] = {"_max_model_len_retry_count": 0, "_max_num_seqs_retry_count": 0}
        proc = _try_start(kv_cache_sent_mb, plan_overrides=explicit_probe_overrides)
        if proc is None:
            partial.error = f"Model failed to start with KV cache " f"{_format_kv_mb(kv_cache_sent_mb)} on tp={tp}"
            _override_error_if_unsupported()
            logger.warning("  ERROR: %s", partial.error)
            return partial

        # Explicit KV produces a single point on the curve using the resolved
        # max_model_len (injected or default).
        explicit_max = int(explicit_probe_overrides.get("_resolved_max_model_len") or plan.get("max_model_len") or 0)
        if explicit_max > 0:
            partial.kv_max_model_len_pairs = [(kv_cache_sent_mb, explicit_max)]
            partial.max_model_len = explicit_max
        explicit_seqs = int(explicit_probe_overrides.get("_resolved_max_num_seqs") or 0)
        if explicit_seqs > 0:
            resolved_max_num_seqs = explicit_seqs

    partial.kv_cache_sent_mb = kv_cache_sent_mb
    partial.min_kv_cache_mb = min_kv_observed_mb
    partial.max_kv_cache_mb = max_kv_observed_mb
    # Keep legacy compatibility field populated from the pair curve when present.
    if partial.kv_max_model_len_pairs and partial.max_model_len <= 0:
        partial.max_model_len = max(mml for _, mml in partial.kv_max_model_len_pairs)
    # Same for a Mamba/SSM --max-num-seqs cap injected during the search.
    if resolved_max_num_seqs > 0:
        partial.max_num_seqs = int(resolved_max_num_seqs)

    if cancel_event is not None and cancel_event.is_set():
        partial.error = "cancelled"
        return partial

    try:
        # Phase 2.5 — Warmup with a 1-token completion. Forces:
        #   • CUDA graph capture (when enforce_eager=False)
        #   • FlashInfer kernel JIT + workspace allocation
        #   • Triton autotune for the model's attention shapes
        #   • Real KV cache page allocation (vs lazy)
        # Without this, the awake VRAM sample below misses the peak the
        # planner actually needs to budget for at runtime.
        if eager_mode:
            logger.info("  [2.5/6] Warming up engine (1-token completion, eager mode)...")
        else:
            logger.info(
                "  [2.5/6] Warming up engine (1-token completion, capturing CUDA graphs — may take a couple minutes)..."
            )
        warmup_t0 = time.perf_counter()
        warmup_ok = warmup_inference(base_url, model, timeout_s=600.0)
        warmup_dt = time.perf_counter() - warmup_t0
        if warmup_ok:
            logger.info(
                "        warmup done in %.1fs — graphs/JIT/KV pools allocated",
                warmup_dt,
            )
        else:
            logger.warning(
                "        warmup failed (%.1fs) — awake VRAM may underestimate peak",
                warmup_dt,
            )

        # Phase 3 — Measure awake VRAM
        if cancel_event is not None and cancel_event.is_set():
            logger.info("  Calibration cancelled before Phase 3.")
            partial.error = "cancelled"
            return partial
        logger.info("  [3/6] Measuring awake VRAM (settling %.0fs)...", _VRAM_SETTLE_S)
        time.sleep(_VRAM_SETTLE_S)
        try:
            awake_total_mb = sample_vram_mb(gpu_indices)
        except Exception as exc:
            partial.error = f"nvidia-smi awake failed: {exc}"
            logger.warning("  ERROR: %s", partial.error)
            return partial
        loaded_vram_mb = max(awake_total_mb - baseline_mb, 0.0)
        # base_residency_mb is the full loaded footprint (weights + KV).
        # The scheduler uses it directly — no separate KV addition on top.
        base_residency_mb = loaded_vram_mb
        logger.info(
            "        awake total = %.0f MB  →  loaded delta = %.0f MB",
            awake_total_mb,
            loaded_vram_mb,
        )
        logger.info(
            "        base_residency = %.0f MB  (= loaded, includes %.0f MB KV)",
            base_residency_mb,
            kv_cache_sent_mb,
        )

        # Phase 4 — Sleep the model (with host-RAM transient sampling)
        if cancel_event is not None and cancel_event.is_set():
            logger.info("  Calibration cancelled before Phase 4.")
            partial.error = "cancelled"
            return partial
        logger.info("  [4/6] Sleeping model (level=%d)...", sleep_level)
        sleep_url = f"{base_url}/sleep?level={sleep_level}"
        with _track_host_ram_transient() as host_ram_probe:
            status, _ = _post(sleep_url, timeout_s=_SLEEP_TIMEOUT_S)
            if status not in (200, 204):
                partial.error = f"/sleep returned HTTP {status}"
                logger.warning("  ERROR: %s", partial.error)
                return partial
            try:
                wait_sleep_state(base_url, True, _SLEEP_TIMEOUT_S)
            except TimeoutError as exc:
                partial.error = str(exc)
                logger.warning("  ERROR: %s", partial.error)
                return partial

        sleep_transient_mb = host_ram_probe["transient_mb"]
        sleep_baseline_mb = host_ram_probe["baseline_mb"]
        if sleep_transient_mb is not None and sleep_baseline_mb is not None:
            logger.info(
                "        sleep_l%d transient host RAM: baseline_available=%.0fMB, " "peak_consumption=%.0fMB",
                sleep_level,
                sleep_baseline_mb,
                sleep_transient_mb,
            )
        else:
            logger.info(
                "        sleep_l%d transient host RAM: /proc/meminfo unavailable — skipped",
                sleep_level,
            )

        # Phase 5 — Measure sleeping VRAM. Sample twice with a settle between
        # samples and take the max. CuMemAllocator's release is asynchronous;
        # a single-shot sample can read mid-release and underestimate the
        # residual (which leads to wake-time OOM when the planner trusts an
        # artificially low value). The first sample is required; the second
        # is a refinement and falls back silently if it fails.
        if cancel_event is not None and cancel_event.is_set():
            logger.info("  Calibration cancelled before Phase 5.")
            partial.error = "cancelled"
            return partial
        logger.info(
            "  [5/6] Measuring sleeping VRAM (settling %.0fs, double-sample)...",
            _VRAM_SETTLE_S,
        )
        time.sleep(_VRAM_SETTLE_S)
        try:
            s1 = sample_vram_mb(gpu_indices)
        except Exception as exc:
            partial.error = f"nvidia-smi sleep failed: {exc}"
            logger.warning("  ERROR: %s", partial.error)
            return partial
        time.sleep(3.0)
        s2: float | None = None
        try:
            s2 = sample_vram_mb(gpu_indices)
        except Exception as exc:
            logger.info("        re-sample skipped (%s) — using single sample", exc)
        sleeping_total_mb = max(s1, s2) if s2 is not None else s1
        sleeping_residual_mb = max(sleeping_total_mb - baseline_mb, 0.0)
        if s2 is not None:
            logger.info(
                "        sleeping samples = %.0f / %.0f MB  →  max delta = %.0f MB",
                s1,
                s2,
                sleeping_residual_mb,
            )
        else:
            logger.info(
                "        sleeping sample = %.0f MB  →  delta = %.0f MB",
                s1,
                sleeping_residual_mb,
            )

        logger.info("  Results:")
        logger.info(
            "    base_residency_mb    = %.0f MB  (= full loaded VRAM, weights + KV)",
            base_residency_mb,
        )
        logger.info(
            "    kv_budget_mb         = %.0f MB  (KV portion, for auditing)",
            kv_cache_sent_mb,
        )
        logger.info(
            "    sleeping_residual_mb = %.0f MB  (measured independently)",
            sleeping_residual_mb,
        )
        logger.info(
            "    Scheduler uses base_residency directly — no KV added on top",
        )

        return CalibrationResult(
            model=model,
            tensor_parallel_size=tp,
            gpu_devices=gpu_devices,
            kv_cache_sent_mb=kv_cache_sent_mb,
            success=True,
            loaded_vram_mb=loaded_vram_mb,
            sleeping_residual_mb=sleeping_residual_mb,
            base_residency_mb=base_residency_mb,
            calibrated_at=time.time(),
            enforce_eager=eager_mode,
            sleep_l1_transient_host_ram_mb=(sleep_transient_mb if sleep_level == 1 else None),
            sleep_l2_transient_host_ram_mb=(sleep_transient_mb if sleep_level == 2 else None),
            min_kv_cache_mb=min_kv_observed_mb,
            max_kv_cache_mb=max_kv_observed_mb,
            max_model_len=partial.max_model_len,
            kv_max_model_len_pairs=partial.kv_max_model_len_pairs,
            max_num_seqs=partial.max_num_seqs,
        )

    finally:
        logger.info("  Stopping vLLM...")
        stop_vllm(proc)
        # Kill any orphaned TP workers left behind by CUDA/NCCL crashes during
        # the binary search.  Process-group kill handles the happy path, but
        # crashes can leave detached workers holding GPU memory.
        _kill_stale_vllm_workers()
        # Let the GPU release memory before the next model
        logger.info("  Waiting %.0fs for GPU memory release...", _VRAM_SETTLE_S)
        time.sleep(_VRAM_SETTLE_S)


# ---------------------------------------------------------------------------
# Profile persistence (mirrors ModelProfileRegistry format)
# ---------------------------------------------------------------------------


def result_to_profile_dict(r: CalibrationResult) -> dict[str, Any]:
    """Build a profile dict compatible with ``ModelProfileRecord.to_dict()``.

    ``base_residency_mb`` is the full loaded VRAM (weights + KV cache).
    The planner uses it directly — no separate KV addition for calibrated profiles.
    ``kv_budget_mb`` is stored for auditing only.
    """
    return {
        "loaded_vram_mb": round(r.loaded_vram_mb, 1),
        "sleeping_residual_mb": round(r.sleeping_residual_mb, 1),
        "disk_size_bytes": None,
        "base_residency_mb": round(r.base_residency_mb, 1),
        "kv_budget_mb": round(r.kv_cache_sent_mb, 1),
        "min_kv_cache_mb": (round(r.min_kv_cache_mb, 1) if r.min_kv_cache_mb > 0 else None),
        "max_kv_cache_mb": (round(r.max_kv_cache_mb, 1) if r.max_kv_cache_mb > 0 else None),
        "engine": "vllm",
        "observed_gpu_memory_utilization": None,
        "min_gpu_memory_utilization_to_load": None,
        "tensor_parallel_size": r.tensor_parallel_size,
        "kv_per_token_bytes": None,
        "max_context_length": None,
        "measurement_count": 1,
        "last_measured_epoch": r.calibrated_at,
        "residency_source": "calibrated",
        "enforce_eager_at_calibration": r.enforce_eager,
        "sleep_l1_transient_host_ram_mb": (
            round(r.sleep_l1_transient_host_ram_mb, 1) if r.sleep_l1_transient_host_ram_mb is not None else None
        ),
        "sleep_l2_transient_host_ram_mb": (
            round(r.sleep_l2_transient_host_ram_mb, 1) if r.sleep_l2_transient_host_ram_mb is not None else None
        ),
        # Not part of ModelProfileRecord but useful for auditing
        "_calibration_kv_cache_mb": round(r.kv_cache_sent_mb, 1),
        # Discovered KV cache size for use by the lane manager at runtime
        "calibration_kv_cache_memory_bytes": _format_kv_mb(r.kv_cache_sent_mb),
        # --max-model-len that calibration auto-injected because the operator's
        # pinned KV budget couldn't fit one request at the model's default
        # max_seq_len. 0 / omitted means the model's default fit and no flag
        # was passed. Mirrors ``calibration_kv_cache_memory_bytes`` — same
        # "value that the successful probe actually used" semantics.
        "calibration_max_model_len": int(r.max_model_len) if r.max_model_len else None,
        # Per-KV max_model_len sweep captured during calibration, each point
        # annotated with the achievable concurrency (``parallelity`` factor =
        # kv_cache_tokens / max_model_len). Falls back to the un-annotated pairs
        # for legacy results that predate parallelity capture.
        "kv_cache_to_max_model_len_pairs": (
            [
                {
                    "kv_mb": round(kv_mb, 1),
                    "max_model_len": int(max_model_len),
                    "parallelity": (round(float(parallelity), 3) if parallelity else None),
                }
                for kv_mb, max_model_len, parallelity in r.kv_max_model_len_parallelity_pairs
            ]
            if r.kv_max_model_len_parallelity_pairs
            else (
                [
                    {"kv_mb": round(kv_mb, 1), "max_model_len": int(max_model_len)}
                    for kv_mb, max_model_len in (r.kv_max_model_len_pairs or [])
                ]
                or None
            )
        ),
        # --max-num-seqs that calibration auto-injected for a hybrid Mamba/SSM
        # model whose state-cache pool was smaller than vLLM's default 1024.
        # None/omitted means no cap was needed. The lane spawner reuses it so
        # production runs with the same ceiling the successful probe proved.
        "calibration_max_num_seqs": int(r.max_num_seqs) if r.max_num_seqs else None,
    }


def load_existing_profiles(profiles_path: Path) -> dict[str, Any]:
    if not profiles_path.exists():
        return {}
    try:
        with profiles_path.open() as f:
            data = yaml.safe_load(f) or {}
        return dict(data.get("model_profiles") or {})
    except Exception as exc:
        logger.warning("Could not parse existing profiles (%s): %s", profiles_path, exc)
        return {}


def save_profiles(profiles_path: Path, profiles: dict[str, Any]) -> None:
    profiles_path.parent.mkdir(parents=True, exist_ok=True)
    with profiles_path.open("w") as f:
        yaml.safe_dump({"model_profiles": profiles}, f, default_flow_style=False)


# ---------------------------------------------------------------------------
# Config parsing (mirrors models.py LogosConfig._parse_capabilities)
# ---------------------------------------------------------------------------


def plans_from_config(config_path: Path) -> list[dict[str, Any]]:
    """Read ``capabilities_models`` from *config.yml* and return calibration plans."""
    with config_path.open() as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    logos = raw.get("logos") or {}
    caps_raw = logos.get("capabilities_models") or []
    caps_overrides: dict[str, dict] = dict(logos.get("capabilities_overrides") or {})
    vllm_model_overrides: dict[str, dict] = ((raw.get("engines") or {}).get("vllm") or {}).get("model_overrides") or {}

    plans: list[dict[str, Any]] = []
    for entry in caps_raw:
        if isinstance(entry, str):
            plan: dict[str, Any] = {"model": entry}
        elif isinstance(entry, dict):
            plan = dict(entry)
            # config format: top-level key is the model name when no "model:" key
            if "model" not in plan:
                model_name = next(iter(plan), None)
                if model_name:
                    plan = {**plan, "model": model_name}
        else:
            continue

        model = plan.get("model", "")
        if not model:
            continue

        # Merge capabilities_overrides (don't override explicit plan values)
        for k, v in (caps_overrides.get(model) or {}).items():
            plan.setdefault(k, v)

        # Merge vllm model_overrides (quantization, disable_custom_all_reduce, etc.)
        for k, v in (vllm_model_overrides.get(model) or {}).items():
            # Only merge fields relevant to calibration (skip runtime-only flags)
            if k in (
                "quantization",
                "dtype",
                "kv_cache_dtype",
                "enforce_eager",
                "max_model_len",
                "max_num_seqs",
                "disable_custom_all_reduce",
            ):
                plan.setdefault(k, v)

        plans.append(plan)

    return plans


# ---------------------------------------------------------------------------
# High-level auto-calibration for use by main.py
# ---------------------------------------------------------------------------


def _max_tp_for_plan(plan: dict[str, Any], available_gpus: int) -> int:
    """Return the maximum tensor_parallel_size allowed for *plan*.

    TP must be a power of 2 for most model architectures (attention heads
    must be evenly divisible).  Round down to the largest power of 2 that
    fits within the available GPUs.
    """
    gpu_devices = str(plan.get("gpu_devices") or "").strip().lower()
    if not gpu_devices or gpu_devices == "all":
        n = available_gpus
    else:
        n = len([x for x in gpu_devices.split(",") if x.strip().isdigit()])
    # Largest power of 2 ≤ n  (e.g. 3 → 2, 5 → 4, 7 → 4, 8 → 8)
    if n < 1:
        return 1
    return 1 << (n.bit_length() - 1)


def _try_calibrate(
    plan: dict[str, Any],
    *,
    vllm_binary: str,
    port: int,
    log_dir: Path,
    sleep_level: int,
    ready_timeout_s: float,
    nccl_p2p_available: bool = False,
    hf_home: str | None = None,
    model_cache: Any | None = None,
    cancel_event: threading.Event | None = None,
) -> CalibrationResult:
    """Call ``calibrate_model`` with exception → failure conversion."""
    model_name = plan["model"]
    try:
        return calibrate_model(
            plan,
            vllm_binary=vllm_binary,
            port=port,
            log_dir=log_dir,
            sleep_level=sleep_level,
            ready_timeout_s=ready_timeout_s,
            nccl_p2p_available=nccl_p2p_available,
            hf_home=hf_home,
            model_cache=model_cache,
            cancel_event=cancel_event,
        )
    except Exception as exc:
        logger.warning("Calibration failed for %s: %s", model_name, exc)
        return CalibrationResult(
            model=model_name,
            tensor_parallel_size=int(plan.get("tensor_parallel_size", 1)),
            gpu_devices=str(plan.get("gpu_devices") or ""),
            kv_cache_sent_mb=0.0,
            success=False,
            error=str(exc),
            enforce_eager=bool(plan.get("enforce_eager", False)),
        )


def calibrate_with_tp_escalation(
    plan: dict[str, Any],
    *,
    vllm_binary: str,
    port: int,
    log_dir: Path,
    sleep_level: int,
    ready_timeout_s: float,
    nccl_p2p_available: bool = False,
    model_cache: Any | None = None,
    available_gpus: int | None = None,
    cancel_event: threading.Event | None = None,
) -> CalibrationResult:
    """Calibrate one model using a max-first, search-down TP strategy.

    Shared by ``auto_calibrate_models`` (boot-time) and the server-orchestrated
    ``start_calibration`` path so both behave identically:

    1. Try ``max_tp`` first (fail fast on models that can't run at all).
    2. Auto-retry with ``--trust-remote-code`` when vLLM demands it.
    3. On max-tp failure, fall back to the configured tp (handles head-count
       divisibility quirks).
    4. On max-tp success, binary-search down to the smallest tp that still
       works — saves GPU resources at runtime.

    ``available_gpus`` defaults to the host's current GPU count.
    """
    model_name = plan["model"]

    if available_gpus is None:
        try:
            available_gpus = len(query_gpu_vram())
        except Exception:
            available_gpus = 1

    original_tp = int(plan.get("tensor_parallel_size", 1))
    max_tp = _max_tp_for_plan(plan, available_gpus)

    # RAM caching is deferred: calibrate_model triggers it on the first
    # actual vLLM spawn so we don't waste time copying when all probes are
    # blacklisted.  Pass the cache object through; it will call
    # ensure_cached_sync only when needed.
    _mc = model_cache if (model_cache is not None and getattr(model_cache, "enabled", False)) else None
    cal_kwargs: dict[str, Any] = dict(
        vllm_binary=vllm_binary,
        port=port,
        log_dir=log_dir,
        sleep_level=sleep_level,
        ready_timeout_s=ready_timeout_s,
        nccl_p2p_available=nccl_p2p_available,
        model_cache=_mc,
        cancel_event=cancel_event,
    )

    tp = max_tp
    current_plan = {**plan, "tensor_parallel_size": tp}
    result = _try_calibrate(current_plan, **cal_kwargs)

    # Auto-retry with --trust-remote-code when vLLM demands it.
    # vLLM phrasings seen in the wild:
    #   "Please pass the argument `trust_remote_code=True`..."
    #   "The repository ... contains custom code which must be executed..."
    _err = result.error or ""
    if not result.success and ("trust_remote_code=True" in _err or "contains custom code" in _err):
        logger.info(
            "  %s requires trust_remote_code — adding flag and retrying",
            model_name,
        )
        extra = list(plan.get("extra_args") or [])
        if "--trust-remote-code" not in extra:
            extra.append("--trust-remote-code")
        plan = {**plan, "extra_args": extra}
        current_plan = {**plan, "tensor_parallel_size": tp}
        result = _try_calibrate(current_plan, **cal_kwargs)

    # If max tp fails, try the configured (original) tp before giving up.
    # Models may have attention-head counts that aren't divisible by max_tp
    # (e.g. 64 heads on 3 GPUs) but work fine at the configured tp.
    _fatal = "does not recognize this architecture" in (result.error or "") or "Cannot access gated repo" in (
        result.error or ""
    )
    if not result.success and not _fatal and tp > original_tp:
        logger.info(
            "  %s failed at max tp=%d — falling back to configured tp=%d",
            model_name,
            tp,
            original_tp,
        )
        tp = original_tp
        current_plan = {**plan, "tensor_parallel_size": tp}
        result = _try_calibrate(current_plan, **cal_kwargs)

    if not result.success or _fatal:
        return result

    # Max tp succeeded — now binary-search down to find minimum tp.
    if tp > original_tp:
        logger.info(
            "  %s works at tp=%d — searching for minimum tp (from %d)",
            model_name,
            tp,
            original_tp,
        )
    best_result = result
    best_tp = tp

    # Binary search: try progressively smaller tp values.
    # tp must be a power of 2 in vLLM, so we halve each step.
    low_tp = original_tp
    high_tp = tp
    while low_tp < high_tp:
        if cancel_event is not None and cancel_event.is_set():
            break
        mid_tp = high_tp // 2
        if mid_tp < low_tp:
            break
        logger.info(
            "  %s trying tp=%d (search range %d–%d)",
            model_name,
            mid_tp,
            low_tp,
            high_tp,
        )
        mid_plan = {**plan, "tensor_parallel_size": mid_tp}
        mid_result = _try_calibrate(mid_plan, **cal_kwargs)
        if mid_result.success:
            best_result = mid_result
            best_tp = mid_tp
            high_tp = mid_tp
        else:
            low_tp = mid_tp * 2

    if best_tp != original_tp:
        logger.info(
            "  %s optimal tp=%d (configured=%d, max=%d)",
            model_name,
            best_tp,
            original_tp,
            max_tp,
        )

    return best_result


def auto_calibrate_models(
    uncalibrated: list[str],
    config_path: Path,
    state_dir: Path,
    *,
    vllm_binary: str = _DEFAULT_VLLM,
    port: int = _CALIBRATION_PORT,
    sleep_level: int = 1,
    ready_timeout_s: float = _READY_TIMEOUT_S,
    nccl_p2p_available: bool = False,
    model_cache: Any | None = None,
) -> dict[str, CalibrationResult]:
    """Calibrate a list of uncalibrated models and persist results.

    Returns a dict mapping model_name -> CalibrationResult.
    Only calibrates models in the *uncalibrated* list.

    Uses a **max-first strategy**: each model is first tested with the
    maximum available ``tensor_parallel_size`` to quickly verify it can
    run at all.  If that succeeds, a binary search finds the smallest
    tp that still works, saving GPU resources at runtime.
    """
    # Load plans from config
    if config_path.exists():
        all_plans = plans_from_config(config_path)
    else:
        all_plans = []

    # Build a lookup of plans by model name
    plan_by_model: dict[str, dict[str, Any]] = {}
    for p in all_plans:
        plan_by_model[p["model"]] = p

    # Filter to uncalibrated models only; create minimal plans for unknown ones
    plans: list[dict[str, Any]] = []
    for name in uncalibrated:
        if name in plan_by_model:
            plans.append(plan_by_model[name])
        else:
            plans.append({"model": name})

    if not plans:
        logger.info("No uncalibrated models to calibrate.")
        return {}

    # Detect available GPU count for tp escalation
    try:
        gpu_snap = query_gpu_vram()
        available_gpus = len(gpu_snap)
    except Exception:
        available_gpus = 1

    profiles_path = state_dir / _PROFILES_FILE
    existing_profiles = load_existing_profiles(profiles_path)
    log_dir = state_dir / "calibration_logs"

    logger.info(
        "Auto-calibration: %d model(s) to calibrate, %d GPU(s) available",
        len(plans),
        available_gpus,
    )
    for p in plans:
        logger.info(
            "  %s  tp=%s  gpu_devices=%s",
            p["model"],
            p.get("tensor_parallel_size", 1),
            p.get("gpu_devices") or "all",
        )

    results: dict[str, CalibrationResult] = {}

    for plan in plans:
        model_name = plan["model"]
        result = calibrate_with_tp_escalation(
            plan,
            vllm_binary=vllm_binary,
            port=port,
            log_dir=log_dir,
            sleep_level=sleep_level,
            ready_timeout_s=ready_timeout_s,
            nccl_p2p_available=nccl_p2p_available,
            model_cache=model_cache,
            available_gpus=available_gpus,
        )
        results[model_name] = result

        if result.success:
            existing_profiles[model_name] = result_to_profile_dict(result)
            # Persist after every success so a later failure doesn't lose results
            save_profiles(profiles_path, existing_profiles)
            logger.info("  Saved profile for %s → %s", model_name, profiles_path)
        else:
            logger.warning(
                "Calibration unsuccessful for %s: %s",
                model_name,
                result.error,
            )

    ok = [r for r in results.values() if r.success]
    fail = [r for r in results.values() if not r.success]
    logger.info("Auto-calibration complete: %d/%d succeeded", len(ok), len(ok) + len(fail))
    if fail:
        for r in fail:
            logger.warning("  Failed: %s — %s", r.model, r.error)

    return results

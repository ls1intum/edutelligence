"""Node-level health sensors for the LogosWorkerNode.

Two distinct failure axes that the kv-cache binary search and the
per-command / per-model blacklists cannot recover from:

  1. GPU sensor — ``nvidia-smi`` reports ``[Error]`` or ``N/A`` for any
     queried memory field. This usually means a card has fallen off the
     PCIe bus, ECC is in an unrecoverable state, or the driver lost track
     of it. The fix is always operator action (reseat the card, reboot).

  2. Storage sensor — the HuggingFace cache directory returns ``EIO`` /
     ``EROFS`` on ``listdir``/``stat``. Caused by network-block-device
     hiccups, Ceph PG recovery, dying disks, etc. Until ops intervenes,
     every vLLM spawn that needs to read a model from cache will fail —
     and previously (before this module) each failure was misclassified
     as a per-command OOM, polluting the blacklist with up to a hundred
     junk lines during a single multi-minute outage (deioma 2026-06-04).

The bridge calls :func:`evaluate_node_health` at heartbeat time and
includes the result in :class:`WorkerRuntimeStatus`. The server logs
loudly on any transition into ``healthy=False`` and the calibration
orchestrator stops scheduling work on unhealthy nodes.

Recovery is automatic: the sensors are stateless and re-checked each
heartbeat. As soon as the underlying issue clears (e.g. operator
remounts ``/mnt/ceph`` after a Ceph reconnect), the next heartbeat will
flip the node back to healthy and the orchestrator resumes scheduling.
No worker restart required.

Adding a sensor: append a ``_check_<name>`` function returning a
``SensorResult`` and register it in :data:`_SENSORS`. Keep each sensor
cheap (≤ a few hundred ms) — the heartbeat path runs them every cycle.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SensorResult:
    """One sensor's read. ``state="ok"`` means healthy; anything else
    is a short kebab-case reason code surfaced to ops."""

    state: str  # "ok" | "<kebab-case-reason>"
    detail: str = ""  # human-readable diagnosis (paths, error messages, …)


@dataclass
class NodeHealthStatus:
    """Aggregated health snapshot for one heartbeat tick."""

    healthy: bool
    checked_at: str  # ISO-8601 UTC timestamp
    sensors: dict[str, dict[str, str]] = field(default_factory=dict)
    # Top-level reason — first failing sensor's reason code. Convenient
    # for callers that just want one string to log / display without
    # walking the per-sensor dict.
    reason_code: str | None = None
    reason_detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "checked_at": self.checked_at,
            "sensors": dict(self.sensors),
            "reason_code": self.reason_code,
            "reason_detail": self.reason_detail,
        }


# ---------------------------------------------------------------------------
# GPU sensor — nvidia-smi ERR / N/A
# ---------------------------------------------------------------------------


_GPU_ERROR_TOKENS = ("[Error]", "ERR!", "[ERR!]", "Unknown Error", "[Unknown Error]")


def _is_gpu_error_token(value: str) -> bool:
    """nvidia-smi shorthand for "this sensor is wedged" — distinct from
    legitimate ``[N/A]`` which several fields return on hardware that
    simply doesn't expose them (e.g. fan speed on passively-cooled cards)."""
    stripped = value.strip()
    return stripped in _GPU_ERROR_TOKENS


def _check_gpu() -> SensorResult:
    """Return ``state="ok"`` when nvidia-smi reports clean values for
    every visible GPU; otherwise ``"gpu-error"`` (some field is literally
    ``[Error]`` / ``ERR!``) or ``"gpu-na"`` (a *memory* field is ``N/A``).

    Two failure modes to detect:

    * Memory fields unreadable (``total/used/free``): the driver lost
      track of the device entirely. ``[Error]``, ``N/A``, and ``ERR!``
      are all wedge signals here because memory should always be
      readable on a healthy GPU.

    * Telemetry-only fields unreadable (``power.draw``, ``fan.speed``,
      ``temperature.gpu``): observed on RTX 6000 Ada / Quadro RTX 5000
      after a GSP RPC failure — memory still queries fine but Pwr/Fan
      flip to ``ERR!`` and any subsequent CUDA context allocation
      returns ``cudaErrorDevicesUnavailable``. We treat ``[Error]`` /
      ``ERR!`` on these fields as a wedge, but *not* ``N/A`` (legit on
      some headless / fanless models).

    All three states are non-recoverable from the worker's side. The
    [[gpu_watchdog]] picks this up and reboots the host.

    Misses nvidia-smi being absent / non-executable entirely — that's
    expected on dev machines and not what this sensor is for.
    """
    try:
        raw = subprocess.check_output(
            [
                "nvidia-smi",
                ("--query-gpu=index,memory.total,memory.used,memory.free," "power.draw,fan.speed,temperature.gpu"),
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return SensorResult(state="ok", detail="nvidia-smi not installed (dev host)")
    except subprocess.CalledProcessError as exc:
        return SensorResult(
            state="gpu-query-failed",
            detail=f"nvidia-smi exited {exc.returncode}: {exc.output!r}",
        )
    except subprocess.TimeoutExpired:
        # nvidia-smi hanging usually means the driver is stuck — worth
        # surfacing as unhealthy because it'll block calibration too.
        return SensorResult(state="gpu-query-timeout", detail="nvidia-smi did not respond within 10s")

    # Memory fields: ERR! / [Error] / N/A all count as wedge.
    # Telemetry fields: only ERR! / [Error] count (N/A is legit on some HW).
    memory_fields = ("total", "used", "free")
    telemetry_fields = ("power", "fan", "temp")
    bad_gpus: list[str] = []
    for line in raw.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 7:
            continue
        idx = parts[0]
        for name, value in zip(memory_fields, parts[1:4]):
            if _is_gpu_error_token(value) or value.upper() == "N/A":
                bad_gpus.append(f"GPU{idx}.{name}={value!r}")
        for name, value in zip(telemetry_fields, parts[4:7]):
            if _is_gpu_error_token(value):
                bad_gpus.append(f"GPU{idx}.{name}={value!r}")
    if bad_gpus:
        any_error_token = any(t in entry for entry in bad_gpus for t in ("Error", "ERR!", "Unknown"))
        return SensorResult(
            state="gpu-error" if any_error_token else "gpu-na",
            detail=(
                f"nvidia-smi reported unreadable fields for {len(bad_gpus)} entry(s): "
                + ", ".join(bad_gpus[:10])
                + ("…" if len(bad_gpus) > 10 else "")
                + ". Card likely fell off the PCIe bus / driver wedged — reboot required."
            ),
        )
    return SensorResult(state="ok")


# ---------------------------------------------------------------------------
# Storage sensor — HF cache readability
# ---------------------------------------------------------------------------


# Paths probed for read access. The first one that actually exists is
# the one we validate; missing paths are skipped (a worker without an HF
# cache is just one without that sensor — not unhealthy).
_STORAGE_PATHS_TO_PROBE: tuple[Path, ...] = (
    Path("/usr/share/ollama/.ollama/models/.hf_cache/hub"),  # production container path
    Path("/usr/share/ollama/.ollama/models/.hf_cache"),
    Path(os.environ.get("HF_HOME", "")) if os.environ.get("HF_HOME") else Path(),
    Path(os.environ.get("HF_HUB_CACHE", "")) if os.environ.get("HF_HUB_CACHE") else Path(),
)


def _check_storage() -> SensorResult:
    """Return ``state="ok"`` when the HF cache directory is readable;
    otherwise ``"filesystem-eio"`` (EIO on read), ``"filesystem-readonly"``
    (the mount is read-only), or ``"filesystem-missing"`` (none of the
    expected paths exist — usually a misconfigured worker).

    Cheap: a single ``os.listdir`` call against the first existing
    candidate path. The HF cache is the most failure-prone storage
    dependency in production because it's typically backed by a network
    block device (Ceph RBD via nbd).
    """
    probed: list[Path] = [p for p in _STORAGE_PATHS_TO_PROBE if str(p) and p.exists()]
    if not probed:
        # No HF cache configured on this host — not a failure. Workers
        # without a model cache (e.g. ollama-only) are healthy.
        return SensorResult(state="ok", detail="no HF cache path configured")

    target = probed[0]
    try:
        # listdir touches the directory inode and the dirent block — same
        # I/O path that triggered the deioma EIO storm. Bounded cost
        # because we don't read file contents.
        os.listdir(target)
        return SensorResult(state="ok")
    except OSError as exc:
        if exc.errno == 5:  # EIO
            return SensorResult(
                state="filesystem-eio",
                detail=(
                    f"listdir({target}) failed with EIO (Errno 5). "
                    "The backing storage is degraded. Check `dmesg | grep -E 'nbd|EXT4'` "
                    "and either restore the device or reboot the node."
                ),
            )
        if exc.errno == 30:  # EROFS
            return SensorResult(
                state="filesystem-readonly",
                detail=(
                    f"listdir({target}) failed because the filesystem is read-only. "
                    "The kernel likely remounted it after I/O errors — investigate the "
                    "backing device or reboot."
                ),
            )
        # Other OSErrors (ENOENT for the leaf only, EACCES, …) shouldn't
        # mark the node as unhealthy. We already short-circuited on
        # ENOENT for the parent above; any remaining error here is
        # surfaced as a generic but non-fatal warning.
        return SensorResult(
            state="ok",
            detail=f"storage probe noise (errno={exc.errno}): {exc}",
        )


# ---------------------------------------------------------------------------
# Registry + entry point
# ---------------------------------------------------------------------------


_SENSORS: tuple[tuple[str, Callable[[], SensorResult]], ...] = (
    ("gpu", _check_gpu),
    ("storage", _check_storage),
)


def evaluate_node_health() -> NodeHealthStatus:
    """Run every registered sensor and produce a fresh aggregated status.

    Stateless — call each heartbeat. The first failing sensor's reason
    code becomes the top-level ``reason_code`` for convenience; the full
    per-sensor breakdown is preserved in ``sensors``.
    """
    sensors: dict[str, dict[str, str]] = {}
    reason_code: str | None = None
    reason_detail: str | None = None
    healthy = True

    for name, check in _SENSORS:
        t0 = time.perf_counter()
        try:
            result = check()
        except Exception as exc:  # noqa: BLE001
            # A sensor that throws shouldn't kill heartbeat — log and
            # treat as a soft 'sensor-error' state.
            logger.warning("node_health: sensor %r raised: %s", name, exc)
            result = SensorResult(state="sensor-error", detail=str(exc))
        sensors[name] = {"state": result.state, "detail": result.detail}
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if elapsed_ms > 500:
            logger.warning("node_health: sensor %r took %.0fms — investigate", name, elapsed_ms)
        if result.state != "ok" and healthy:
            healthy = False
            reason_code = result.state
            reason_detail = result.detail

    return NodeHealthStatus(
        healthy=healthy,
        checked_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        sensors=sensors,
        reason_code=reason_code,
        reason_detail=reason_detail,
    )

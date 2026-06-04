#!/usr/bin/env python3
"""
Logos Benchmark — TTFT, TTLT, GPU Energy per Request

Measures per request:
  TTFT  (Time to First Token)  — client-side, first SSE content delta
  TTLT  (Time to Last Token)   — client-side, stream closed
  Energy (Joules)              — NVIDIA NVML energy counter on the GPU nodes

Architecture
------------
This script runs on the same machine as the Logos server. The actual GPU
work is done by vLLM instances on *separate* GPU nodes. Energy is measured
by SSH-ing into those nodes and running a continuous NVML poller there.

                ┌─────────────────────────────┐
                │  Logos host (this script)   │
                │  ┌──────────┐  ┌─────────┐  │
                │  │ benchmark│  │  Logos  │  │
                │  └──────────┘  └────┬────┘  │
                └───────────────────┼─────────┘
                                    │ HTTP (vLLM API)
              ┌─────────────────────┼─────────────────────┐
              │  GPU node A         │         GPU node B   │
              │  ┌──────────┐   ┌──┴───────┐ ┌──────────┐ │
              │  │NVML poll │   │  vLLM    │ │  vLLM    │ │
              │  │(via SSH) │   │RTX Ada   │ │RTX Ada   │ │
              │  └──────────┘   └──────────┘ └──────────┘ │
              └─────────────────────────────────────────────┘

Supports three scenarios via --scenario:
  logos-sleep    Send to Logos (sleep/idle mode enabled server-side).
  logos-nosleep  Send to Logos (sleep/idle mode disabled server-side).
  ollama         Send directly to Ollama. Uses OLLAMA_MODEL_MAP from
                 benchmark_config.py to translate Logos model names to Ollama
                 tags. No logos_key header is sent.

Requirements (on this machine):
    pip install httpx paramiko numpy matplotlib

Requirements (on each GPU node, installed once with root access):
    pip install nvidia-ml-py

Usage — remote GPU nodes (typical setup):
    python benchmark_logos.py \\
        --scenario logos-sleep \\
        --logos-url http://logos.ase.cit.tum.de \\
        --logos-key YOUR_KEY \\
        --workload workloads/workload_gsm8k_2llm.csv \\
        --gpu-host gpu-node-a gpu-node-b \\
        --gpu-ssh-user ubuntu \\
        --gpu-ssh-key ~/.ssh/id_rsa \\
        --sequential --output-dir results

Usage — local GPU (e.g. direct Ollama on same machine as this script):
    python benchmark_logos.py \\
        --scenario ollama \\
        --logos-url http://localhost:11434 \\
        --workload workloads/workload_gsm8k_2llm.csv \\
        --gpu-indices 0 --sequential

Energy note for concurrent requests:
    Each request reports the GPU energy consumed during its [t_start, t_end]
    window. With concurrent requests the windows overlap — use --sequential
    for clean, non-overlapping attribution.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import importlib.util
import json
import math
import sys
import threading
import time
import warnings as _warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

# ── Optional deps ─────────────────────────────────────────────────────────


try:
    with _warnings.catch_warnings():
        # Both nvidia-ml-py (correct) and the deprecated pynvml package expose
        # the same pynvml module. The deprecated package emits a FutureWarning
        # on import. Suppress it here; requirements.txt pins nvidia-ml-py.
        _warnings.filterwarnings("ignore", category=FutureWarning, message=".*pynvml.*")
        import pynvml as _pynvml
    _NVML = True
except ImportError:
    _NVML = False

try:
    import paramiko as _paramiko

    _PARAMIKO = True
except ImportError:
    _PARAMIKO = False

try:
    import matplotlib
    import numpy as np

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _PLOT = True
except ImportError:
    _PLOT = False


# ── Remote poller script (embedded, sent to GPU nodes via SSH) ────────────
#
# Runs on each GPU node. Continuously streams one line per poll interval:
#   <unix_timestamp> <power_mw> <energy_mj>
# energy_mj = -1 when the hardware counter is unavailable (falls back to
# power-integration only). Uses nvidia-smi as a last resort if pynvml is
# not installed on the node.

_REMOTE_POLLER = r"""
import sys, time, warnings, subprocess
warnings.filterwarnings("ignore", category=FutureWarning)

GPU_INDEX = {gpu_index}
INTERVAL  = {interval:.3f}

use_nvml   = False
has_energy = False

try:
    import pynvml
    pynvml.nvmlInit()
    _h = pynvml.nvmlDeviceGetHandleByIndex(GPU_INDEX)
    use_nvml = True
    try:
        pynvml.nvmlDeviceGetTotalEnergyConsumption(_h)
        has_energy = True
    except Exception:
        pass
except Exception:
    pass

def _read_nvml():
    try:
        p = pynvml.nvmlDeviceGetPowerUsage(_h)
        e = pynvml.nvmlDeviceGetTotalEnergyConsumption(_h) if has_energy else -1
        return p, e
    except Exception:
        return 0, -1

def _read_smi():
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=power.draw",
             "--format=csv,noheader,nounits", f"--id={GPU_INDEX}"],
            text=True, timeout=2.0,
        )
        return int(float(out.strip()) * 1000), -1
    except Exception:
        return 0, -1

_read = _read_nvml if use_nvml else _read_smi

while True:
    t = time.time()
    p_mw, e_mj = _read()
    sys.stdout.write(f"{t:.6f} {p_mw} {e_mj}\n")
    sys.stdout.flush()
    time.sleep(INTERVAL)
"""


# ── Load benchmark_config (optional sibling file) ─────────────────────────


def _load_config_attr(attr: str, default):
    config_path = Path(__file__).parent / "benchmark_config.py"
    if not config_path.exists():
        return default
    try:
        spec = importlib.util.spec_from_file_location("benchmark_config", config_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return getattr(mod, attr, default)
    except Exception:
        return default


# ── Local GPU Tracker (NVML on this machine) ──────────────────────────────


class GPUTracker:
    """
    GPU energy tracking via local NVML calls.
    Use when the GPU is on the same machine as this script (e.g. direct Ollama).
    """

    def __init__(self, device_indices: list[int], poll_interval_ms: float = 100.0):
        self.device_indices = device_indices
        self._poll_s = poll_interval_ms / 1000.0
        self._handles: list = []
        self._use_counter = False
        self._samples: list[tuple[float, float]] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.available = False
        self.method = "none"

    def start(self) -> None:
        if not _NVML:
            print("  [gpu] pynvml not installed — energy measurement disabled.")
            print("        Install with: pip install nvidia-ml-py")
            return
        try:
            _pynvml.nvmlInit()
        except Exception as exc:
            print(f"  [gpu] NVML init failed: {exc}")
            return

        for idx in self.device_indices:
            try:
                h = _pynvml.nvmlDeviceGetHandleByIndex(idx)
                name = _pynvml.nvmlDeviceGetName(h)
                self._handles.append(h)
                print(f"  [gpu] GPU {idx}: {name}")
            except Exception as exc:
                print(f"  [gpu] Cannot open GPU {idx}: {exc}")

        if not self._handles:
            return

        try:
            _pynvml.nvmlDeviceGetTotalEnergyConsumption(self._handles[0])
            self._use_counter = True
            self.method = "counter"
            print("  [gpu] Energy method: hardware counter (nvmlDeviceGetTotalEnergyConsumption)")
        except Exception:
            self.method = "polling"
            print(f"  [gpu] Energy method: power-poll integration ({self._poll_s*1000:.0f} ms interval)")

        self.available = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="gpu-poller")
        self._thread.start()

    def stop(self) -> None:
        if not self.available:
            return
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        try:
            _pynvml.nvmlShutdown()
        except Exception:
            pass

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            t = time.monotonic()
            mw = sum(_pynvml.nvmlDeviceGetPowerUsage(h) for h in self._handles if True)  # errors silently ignored below
            with self._lock:
                self._samples.append((t, mw))
            time.sleep(self._poll_s)

    def _sum_power_mw(self) -> float:
        total = 0.0
        for h in self._handles:
            try:
                total += _pynvml.nvmlDeviceGetPowerUsage(h)
            except Exception:
                pass
        return total

    def _sum_energy_mj(self) -> Optional[float]:
        total = 0.0
        for h in self._handles:
            try:
                total += _pynvml.nvmlDeviceGetTotalEnergyConsumption(h)
            except Exception:
                return None
        return total

    def snapshot_energy_mj(self) -> Optional[float]:
        if not self.available or not self._use_counter:
            return None
        return self._sum_energy_mj()

    def energy_from_counter(self, start_mj: float, end_mj: float) -> float:
        return (end_mj - start_mj) / 1000.0

    def energy_from_samples(self, t_start: float, t_end: float) -> Optional[float]:
        with self._lock:
            samples = list(self._samples)
        window = [(t, p) for t, p in samples if t_start <= t <= t_end]
        if len(window) < 2:
            before = [s for s in samples if s[0] < t_start]
            after = [s for s in samples if s[0] > t_end]
            if before and after and not window:
                avg_mw = (before[-1][1] + after[0][1]) / 2.0
                return avg_mw / 1000.0 * (t_end - t_start)
            return None
        energy_j = 0.0
        for i in range(1, len(window)):
            t0, p0 = window[i - 1]
            t1, p1 = window[i]
            energy_j += (p0 + p1) / 2.0 / 1000.0 * (t1 - t0)
        return energy_j

    def power_samples(self) -> list[tuple[float, float]]:
        with self._lock:
            return list(self._samples)


# ── Remote GPU Tracker (SSH → NVML on GPU nodes) ──────────────────────────


@dataclass
class _RSample:
    """One sample received from the remote poller."""

    remote_wall_t: float  # time.time() on GPU machine
    power_mw: float
    energy_mj: float  # -1 if hardware counter not available


class RemoteGPUTracker:
    """
    GPU energy tracking for nodes accessed via SSH.
    Use when vLLM (and the GPU) is on a different machine from this script.

    At start-up this class:
      1. Opens a paramiko SSH session to each GPU host.
      2. Measures the clock offset between this machine and the GPU node
         (NTP-style round-trip) so remote timestamps can be mapped to local
         monotonic time.
      3. Launches the embedded _REMOTE_POLLER script on the node. The poller
         streams "timestamp power_mw energy_mj" lines until stop() is called.
      4. A background thread per host reads those lines into a local buffer.

    snapshot_energy_mj() returns the sum of the latest energy counter values
    across all hosts. energy_from_samples() integrates power over the request
    window using the buffered samples (converted to local monotonic time).
    """

    def __init__(
        self,
        hosts: list[str],
        ssh_user: str,
        ssh_key_path: Optional[str],
        ssh_port: int,
        gpu_index: int,
        poll_interval_ms: float,
    ):
        self.hosts = hosts
        self._ssh_user = ssh_user
        self._ssh_key_path = ssh_key_path
        self._ssh_port = ssh_port
        self._gpu_index = gpu_index
        self._poll_s = poll_interval_ms / 1000.0

        self._clients: list = []
        self._channels: list = []
        self._all_samples: list[list[_RSample]] = []
        self._locks: list[threading.Lock] = []
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()

        # Clock correlation: local_mono = _mono_start + (remote_wall - _wall_start - _offset[i])
        self._mono_start = 0.0
        self._wall_start = 0.0
        self._offsets: list[float] = []  # clock offset per host (remote - local)

        self.available = False
        self._use_counter = False
        self.method = "none"

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        if not _PARAMIKO:
            print("  [gpu] paramiko not installed — remote GPU measurement disabled.")
            print("        Install with: pip install paramiko")
            return

        self._mono_start = time.monotonic()
        self._wall_start = time.time()

        # Base64-encode the poller script to avoid all shell quoting issues
        script = _REMOTE_POLLER.format(gpu_index=self._gpu_index, interval=self._poll_s)
        encoded = base64.b64encode(script.encode()).decode()
        cmd = f"echo {encoded} | base64 -d | python3 -u"

        ok_hosts = 0
        for host in self.hosts:
            samples: list[_RSample] = []
            lock = threading.Lock()
            try:
                client = _paramiko.SSHClient()
                client.set_missing_host_key_policy(_paramiko.AutoAddPolicy())
                connect_kwargs: dict = dict(
                    hostname=host,
                    port=self._ssh_port,
                    username=self._ssh_user,
                    timeout=15.0,
                    banner_timeout=15.0,
                )
                if self._ssh_key_path:
                    connect_kwargs["key_filename"] = self._ssh_key_path
                client.connect(**connect_kwargs)

                # Measure clock offset (NTP-style single round-trip)
                offset = self._measure_offset(client)
                self._offsets.append(offset)
                print(f"  [gpu] {host}: connected  clock_offset={offset*1000:+.1f} ms")

                # Start remote poller
                transport = client.get_transport()
                channel = transport.open_session()
                channel.exec_command(cmd)
                channel.setblocking(False)

                self._clients.append(client)
                self._channels.append(channel)
                self._all_samples.append(samples)
                self._locks.append(lock)

                t = threading.Thread(
                    target=self._reader,
                    args=(channel, samples, lock, len(self._threads)),
                    daemon=True,
                    name=f"gpu-reader-{host}",
                )
                t.start()
                self._threads.append(t)
                ok_hosts += 1

            except Exception as exc:
                print(f"  [gpu] {host}: connection failed — {exc}")
                self._offsets.append(0.0)

        if ok_hosts == 0:
            return

        # Wait for first samples to arrive so snapshots are immediately usable
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if all(len(s) > 0 for s in self._all_samples if s is not None):
                break
            time.sleep(0.05)

        # Determine energy counter availability from first samples
        for samples, lock in zip(self._all_samples, self._locks):
            with lock:
                if samples and samples[0].energy_mj >= 0:
                    self._use_counter = True
                    break

        self.method = "counter" if self._use_counter else "polling"
        print(
            f"  [gpu] Energy method: {'hardware counter' if self._use_counter else 'power-poll integration'} "
            f"across {ok_hosts} host(s)"
        )
        self.available = True

    def stop(self) -> None:
        self._stop.set()
        for ch in self._channels:
            try:
                ch.close()
            except Exception:
                pass
        for cl in self._clients:
            try:
                cl.close()
            except Exception:
                pass

    # ── internals ─────────────────────────────────────────────────────────

    @staticmethod
    def _measure_offset(client) -> float:
        """Estimate remote_time - local_time via one SSH round-trip."""
        t1 = time.time()
        _, stdout, _ = client.exec_command("python3 -c 'import time; print(time.time())'")
        try:
            remote_t = float(stdout.read().decode().strip())
        except Exception:
            return 0.0
        t2 = time.time()
        return remote_t - (t1 + t2) / 2.0

    def _reader(
        self,
        channel,
        samples: list[_RSample],
        lock: threading.Lock,
        host_idx: int,
    ) -> None:
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = channel.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line_bytes, buf = buf.split(b"\n", 1)
                    line = line_bytes.decode(errors="ignore").strip()
                    if not line:
                        continue
                    parts = line.split()
                    if len(parts) != 3:
                        continue
                    try:
                        s = _RSample(
                            remote_wall_t=float(parts[0]),
                            power_mw=float(parts[1]),
                            energy_mj=float(parts[2]),
                        )
                        with lock:
                            samples.append(s)
                    except ValueError:
                        continue
            except Exception:
                time.sleep(0.01)

    def _to_local_mono(self, remote_wall_t: float, host_idx: int) -> float:
        """Convert a remote wall-clock timestamp to local monotonic time."""
        offset = self._offsets[host_idx] if host_idx < len(self._offsets) else 0.0
        return self._mono_start + (remote_wall_t - offset - self._wall_start)

    # ── public API (same interface as GPUTracker) ─────────────────────────

    def snapshot_energy_mj(self) -> Optional[float]:
        """Sum of the latest energy counter values across all hosts (mJ)."""
        if not self.available or not self._use_counter:
            return None
        total = 0.0
        for samples, lock in zip(self._all_samples, self._locks):
            with lock:
                if not samples:
                    return None
                latest = samples[-1]
                if latest.energy_mj < 0:
                    return None
                total += latest.energy_mj
        return total

    def energy_from_counter(self, start_mj: float, end_mj: float) -> float:
        return (end_mj - start_mj) / 1000.0

    def energy_from_samples(self, t_start: float, t_end: float) -> Optional[float]:
        """Trapezoidal integration of total power across all hosts → Joules."""
        # Build a merged (local_monotonic_t, total_mw) series
        combined: list[tuple[float, float]] = []
        for idx, (samples, lock) in enumerate(zip(self._all_samples, self._locks)):
            with lock:
                snap = list(samples)
            for s in snap:
                lt = self._to_local_mono(s.remote_wall_t, idx)
                combined.append((lt, s.power_mw))

        combined.sort(key=lambda x: x[0])
        # Sum power from all hosts at each time step
        # (since polls from multiple hosts arrive at slightly different times,
        # we keep them as individual points and integrate the aggregated curve)
        window = [(t, p) for t, p in combined if t_start <= t <= t_end]
        if len(window) < 2:
            return None
        energy_j = 0.0
        for i in range(1, len(window)):
            t0, p0 = window[i - 1]
            t1, p1 = window[i]
            energy_j += (p0 + p1) / 2.0 / 1000.0 * (t1 - t0)
        return energy_j

    def power_samples(self) -> list[tuple[float, float]]:
        """All samples as (local_monotonic_t, total_mW) — for timeline chart."""
        combined: list[tuple[float, float]] = []
        for idx, (samples, lock) in enumerate(zip(self._all_samples, self._locks)):
            with lock:
                snap = list(samples)
            for s in snap:
                lt = self._to_local_mono(s.remote_wall_t, idx)
                combined.append((lt, s.power_mw))
        combined.sort(key=lambda x: x[0])
        return combined


# ── Workload ──────────────────────────────────────────────────────────────


@dataclass
class WorkloadEntry:
    request_id: str
    arrival_offset_ms: float
    body: dict
    mode: str = "interactive"
    priority: str = "mid"


_PRIORITY_MAP = {"low": 1, "mid": 5, "high": 10}


def _load_csv(path: Path, model_override: Optional[str]) -> list[WorkloadEntry]:
    entries: list[WorkloadEntry] = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [h.strip().lower() for h in (reader.fieldnames or [])]
        for idx, row in enumerate(reader, 1):
            rid = row.get("request_id") or f"req-{idx:04d}"
            offset = float(row.get("arrival_offset", 0))
            mode = row.get("mode", "interactive").strip().lower()
            priority = row.get("priority", "mid").strip().lower()
            body = json.loads(row.get("body_json", "{}"))
            if model_override:
                body["model"] = model_override
            entries.append(WorkloadEntry(rid, offset, body, mode, priority))
    entries.sort(key=lambda e: e.arrival_offset_ms)
    return entries


def _load_prompts(path: Path, model: str, max_tokens: int, interval_ms: float) -> list[WorkloadEntry]:
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [
        WorkloadEntry(
            request_id=f"req-{i + 1:04d}",
            arrival_offset_ms=i * interval_ms,
            body={
                "model": model,
                "messages": [{"role": "user", "content": line}],
                "max_tokens": max_tokens,
            },
        )
        for i, line in enumerate(lines)
    ]


# ── Request dispatch ──────────────────────────────────────────────────────


@dataclass
class RequestResult:
    request_id: str
    model: str
    mode: str
    priority: str
    status_code: int
    ttft_ms: Optional[float]
    ttlt_ms: Optional[float]
    energy_j: Optional[float]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    error: Optional[str]
    t_start: float
    t_end: float
    sent_at: str
    received_at: str
    scenario: str = ""

    @property
    def success(self) -> bool:
        return bool(self.status_code and 200 <= self.status_code < 400 and not self.error)

    @property
    def tpot_ms(self) -> Optional[float]:
        if (
            self.ttft_ms is not None
            and self.ttlt_ms is not None
            and self.completion_tokens
            and self.completion_tokens > 1
        ):
            return (self.ttlt_ms - self.ttft_ms) / (self.completion_tokens - 1)
        return None

    @property
    def throughput_tok_s(self) -> Optional[float]:
        if self.ttlt_ms and self.completion_tokens:
            return self.completion_tokens / (self.ttlt_ms / 1000.0)
        return None

    @property
    def energy_per_token_mj(self) -> Optional[float]:
        if self.energy_j is not None and self.completion_tokens:
            return self.energy_j / self.completion_tokens * 1000.0
        return None


async def _dispatch(
    client: httpx.AsyncClient,
    base_url: str,
    logos_key: Optional[str],
    entry: WorkloadEntry,
    start_mono: float,
    tracker,  # GPUTracker | RemoteGPUTracker
    sequential: bool,
    scenario: str,
    model_map: dict[str, str],
) -> RequestResult:
    if not sequential:
        wait = (entry.arrival_offset_ms / 1000.0) - (time.monotonic() - start_mono)
        if wait > 0:
            await asyncio.sleep(wait)

    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    payload = {**entry.body, "stream": True}

    is_ollama = scenario == "ollama"
    if is_ollama:
        original_model = str(payload.get("model", ""))
        payload["model"] = model_map.get(original_model, original_model)
        headers = {"Content-Type": "application/json"}
    else:
        payload["mode"] = entry.mode
        payload["priority"] = _PRIORITY_MAP.get(entry.priority.lower(), 5)
        headers = {"Content-Type": "application/json", "logos_key": logos_key or ""}

    ttft_ms: Optional[float] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    error: Optional[str] = None
    model = str(payload.get("model", ""))
    status_code = 0

    e_start = tracker.snapshot_energy_mj()
    t_start = time.monotonic()
    sent_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    try:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            status_code = resp.status_code
            first_token = False

            async for raw in resp.aiter_lines():
                line = raw.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue

                if not model:
                    model = chunk.get("model", "")

                if not first_token:
                    for choice in chunk.get("choices", []):
                        if choice.get("delta", {}).get("content"):
                            ttft_ms = (time.monotonic() - t_start) * 1000.0
                            first_token = True
                            break

                if usage := chunk.get("usage"):
                    prompt_tokens = usage.get("prompt_tokens")
                    completion_tokens = usage.get("completion_tokens")

    except Exception as exc:
        error = str(exc)[:500]

    t_end = time.monotonic()
    e_end = tracker.snapshot_energy_mj()
    received_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    ttlt_ms = (t_end - t_start) * 1000.0

    energy_j: Optional[float] = None
    if tracker.available:
        if e_start is not None and e_end is not None and tracker._use_counter:
            energy_j = tracker.energy_from_counter(e_start, e_end)
        else:
            energy_j = tracker.energy_from_samples(t_start, t_end)

    return RequestResult(
        request_id=entry.request_id,
        model=model,
        mode=entry.mode,
        priority=entry.priority,
        status_code=status_code,
        ttft_ms=ttft_ms,
        ttlt_ms=ttlt_ms,
        energy_j=energy_j,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        error=error,
        t_start=t_start,
        t_end=t_end,
        sent_at=sent_at,
        received_at=received_at,
        scenario=scenario,
    )


# ── Runners ───────────────────────────────────────────────────────────────


def _result_line(r: RequestResult) -> str:
    parts = [
        f"TTFT={r.ttft_ms:.0f}ms" if r.ttft_ms is not None else "TTFT=—",
        f"TTLT={r.ttlt_ms:.0f}ms" if r.ttlt_ms is not None else "TTLT=—",
    ]
    if r.energy_j is not None:
        parts.append(f"E={r.energy_j:.3f}J")
    if not r.success:
        parts.append(f"ERR={r.status_code} {(r.error or '')[:60]}".rstrip())
    return "  ".join(parts)


async def run_sequential(
    workload: list[WorkloadEntry],
    base_url: str,
    logos_key: Optional[str],
    tracker,
    timeout_s: float,
    scenario: str,
    model_map: dict[str, str],
) -> list[RequestResult]:
    results: list[RequestResult] = []
    width = len(str(len(workload)))
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        for i, entry in enumerate(workload):
            print(f"  [{i+1:{width}}/{len(workload)}] {entry.request_id} ... ", end="", flush=True)
            r = await _dispatch(
                client,
                base_url,
                logos_key,
                entry,
                0.0,
                tracker,
                sequential=True,
                scenario=scenario,
                model_map=model_map,
            )
            results.append(r)
            print(_result_line(r), flush=True)
    return results


async def run_concurrent(
    workload: list[WorkloadEntry],
    base_url: str,
    logos_key: Optional[str],
    tracker,
    timeout_s: float,
    max_concurrent: int,
    scenario: str,
    model_map: dict[str, str],
) -> list[RequestResult]:
    sem = asyncio.Semaphore(max_concurrent)
    results: list[RequestResult] = []
    completed = 0
    lock = asyncio.Lock()
    n = len(workload)
    width = len(str(n))

    async with httpx.AsyncClient(timeout=timeout_s) as client:

        async def _run(entry: WorkloadEntry, start_mono: float) -> None:
            nonlocal completed
            async with sem:
                r = await _dispatch(
                    client,
                    base_url,
                    logos_key,
                    entry,
                    start_mono,
                    tracker,
                    sequential=False,
                    scenario=scenario,
                    model_map=model_map,
                )
            async with lock:
                results.append(r)
                completed += 1
                print(f"  [{completed:{width}}/{n}] {r.request_id}  {_result_line(r)}", flush=True)

        start_mono = time.monotonic()
        await asyncio.gather(*[_run(e, start_mono) for e in workload])

    return results


# ── Statistics ────────────────────────────────────────────────────────────


def _pct(vals: list[float], p: float) -> float:
    if not vals:
        return math.nan
    s = sorted(vals)
    k = (len(s) - 1) * p / 100.0
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return s[lo] if lo == hi else s[lo] * (hi - k) + s[hi] * (k - lo)


def _stats(vals: list[float], prefix: str) -> dict:
    if not vals:
        return {f"{prefix}_{s}": math.nan for s in ("mean", "p50", "p95", "p99")}
    return {
        f"{prefix}_mean": sum(vals) / len(vals),
        f"{prefix}_p50": _pct(vals, 50),
        f"{prefix}_p95": _pct(vals, 95),
        f"{prefix}_p99": _pct(vals, 99),
    }


def compute_summary(results: list[RequestResult], scenario: str, energy_method: str) -> dict:
    ok = [r for r in results if r.success]
    fail = len(results) - len(ok)

    ttft = [r.ttft_ms for r in ok if r.ttft_ms is not None]
    ttlt = [r.ttlt_ms for r in ok if r.ttlt_ms is not None]
    tpot = [r.tpot_ms for r in ok if r.tpot_ms is not None]
    energy = [r.energy_j for r in ok if r.energy_j is not None]
    e_tok = [r.energy_per_token_mj for r in ok if r.energy_per_token_mj is not None]
    tput = [r.throughput_tok_s for r in ok if r.throughput_tok_s is not None]

    return {
        "scenario": scenario,
        "energy_method": energy_method,
        "total_requests": len(results),
        "successful_requests": len(ok),
        "failed_requests": fail,
        "error_rate_pct": fail / len(results) * 100 if results else math.nan,
        **_stats(ttft, "ttft_ms"),
        **_stats(ttlt, "ttlt_ms"),
        **_stats(tpot, "tpot_ms"),
        **_stats(energy, "energy_j"),
        **_stats(e_tok, "energy_per_token_mj"),
        "throughput_tok_s_mean": sum(tput) / len(tput) if tput else math.nan,
        "total_prompt_tokens": sum(r.prompt_tokens or 0 for r in ok),
        "total_completion_tokens": sum(r.completion_tokens or 0 for r in ok),
        "total_energy_j": sum(energy) if energy else math.nan,
    }


# ── Output ────────────────────────────────────────────────────────────────


def _f(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    return f"{v:.4f}" if isinstance(v, float) else str(v)


_DETAIL_COLS = [
    "request_id",
    "model",
    "scenario",
    "mode",
    "priority",
    "status_code",
    "ttft_ms",
    "ttlt_ms",
    "tpot_ms",
    "energy_j",
    "energy_per_token_mj",
    "throughput_tok_s",
    "prompt_tokens",
    "completion_tokens",
    "sent_at",
    "received_at",
    "error",
]


def write_detailed(path: Path, results: list[RequestResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_DETAIL_COLS)
        w.writeheader()
        for r in results:
            w.writerow(
                {
                    "request_id": r.request_id,
                    "model": r.model,
                    "scenario": r.scenario,
                    "mode": r.mode,
                    "priority": r.priority,
                    "status_code": r.status_code,
                    "ttft_ms": _f(r.ttft_ms),
                    "ttlt_ms": _f(r.ttlt_ms),
                    "tpot_ms": _f(r.tpot_ms),
                    "energy_j": _f(r.energy_j),
                    "energy_per_token_mj": _f(r.energy_per_token_mj),
                    "throughput_tok_s": _f(r.throughput_tok_s),
                    "prompt_tokens": _f(r.prompt_tokens),
                    "completion_tokens": _f(r.completion_tokens),
                    "sent_at": r.sent_at,
                    "received_at": r.received_at,
                    "error": r.error or "",
                }
            )


def write_summary(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["metric", "value"])
        for k, v in summary.items():
            w.writerow([k, _f(v) if isinstance(v, float) else v])


# ── Charts ────────────────────────────────────────────────────────────────


def _kde_curve(data: list[float], x_grid: "np.ndarray") -> "np.ndarray":
    n = len(data)
    std = float(np.std(data)) or 1.0
    bw = 1.06 * std * n ** (-0.2)
    out = np.zeros_like(x_grid, dtype=float)
    for xi in data:
        out += np.exp(-0.5 * ((x_grid - xi) / bw) ** 2)
    return out / (n * bw * math.sqrt(2 * math.pi))


def _dist_chart(vals: list[float], title: str, xlabel: str, path: Path) -> None:
    if not vals or not _PLOT:
        return
    fig, ax = plt.subplots(figsize=(10, 5))
    n_bins = min(60, max(10, len(vals) // 3))
    ax.hist(vals, bins=n_bins, density=True, alpha=0.6, color="#4C72B0", edgecolor="#1a3a6b", linewidth=0.4)
    x = np.linspace(min(vals) * 0.9, max(vals) * 1.1, 400)
    ax.plot(x, _kde_curve(vals, x), color="#1a3a6b", linewidth=1.8)
    for p, col, lbl in [(50, "#2ca02c", "P50"), (95, "#d62728", "P95"), (99, "#9467bd", "P99")]:
        v = _pct(vals, p)
        ax.axvline(v, color=col, linestyle="--", linewidth=1.4, label=f"{lbl}: {v:.1f}")
    mean_v = sum(vals) / len(vals)
    ax.axvline(mean_v, color="#ff7f0e", linestyle=":", linewidth=1.6, label=f"Mean: {mean_v:.1f}")
    ax.set_title(title, fontsize=13)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Density")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _power_timeline(
    samples: list[tuple[float, float]],
    results: list[RequestResult],
    t0: float,
    path: Path,
) -> None:
    if not _PLOT or not samples:
        return
    ts = [(t - t0) for t, _ in samples]
    pw = [p / 1000.0 for _, p in samples]

    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(ts, pw, color="#2255A0", linewidth=1.0, label="GPU power (W)", zorder=3)
    ax.fill_between(ts, pw, alpha=0.15, color="#2255A0")

    palette = plt.cm.tab20.colors
    for i, r in enumerate(sorted(results, key=lambda x: x.t_start)):
        col = palette[i % len(palette)]
        x0, x1 = r.t_start - t0, r.t_end - t0
        ax.axvspan(x0, x1, alpha=0.10, color=col, zorder=1)
        ax.annotate(
            r.request_id,
            xy=((x0 + x1) / 2, 0),
            xycoords=("data", "axes fraction"),
            xytext=(0, 2),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=5.5,
            color=col,
            rotation=90,
            zorder=4,
        )

    ax.set_xlabel("Elapsed time (s)")
    ax.set_ylabel("Power (W)")
    ax.set_title("GPU Power Timeline with Request Windows")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _scatter_energy_ttlt(results: list[RequestResult], path: Path) -> None:
    if not _PLOT:
        return
    ok = [r for r in results if r.success and r.energy_j is not None and r.ttlt_ms is not None]
    if not ok:
        return
    x = [r.ttlt_ms for r in ok]
    y = [r.energy_j for r in ok]
    tokens = [r.completion_tokens or 1 for r in ok]
    fig, ax = plt.subplots(figsize=(8, 5))
    sc = ax.scatter(x, y, c=tokens, cmap="viridis", alpha=0.75, edgecolors="none", s=40)
    plt.colorbar(sc, ax=ax, label="completion_tokens")
    ax.set_xlabel("TTLT (ms)")
    ax.set_ylabel("Energy (J)")
    ax.set_title("Energy vs TTLT (color = completion tokens)")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _per_model_chart(results: list[RequestResult], metric: str, ylabel: str, path: Path) -> None:
    if not _PLOT:
        return
    ok = [r for r in results if r.success]
    models = sorted({r.model for r in ok})
    data = [[v for r in ok if r.model == m for v in [getattr(r, metric)] if v is not None] for m in models]
    if not any(data):
        return
    fig, ax = plt.subplots(figsize=(max(8, len(models) * 2), 5))
    ax.boxplot(data, tick_labels=[m.split("/")[-1] for m in models], patch_artist=True)
    ax.set_ylabel(ylabel)
    ax.set_title(f"{ylabel} by Model")
    ax.grid(True, alpha=0.25, axis="y")
    plt.xticks(rotation=20, ha="right")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _model_switching_chart(
    results: list[RequestResult],
    t0: float,
    path: Path,
) -> None:
    """Scatter: x = request start time (s since benchmark start), y = TTLT (ms), color = model."""
    if not _PLOT:
        return
    ok = [r for r in results if r.success and r.ttlt_ms is not None]
    if not ok:
        return

    models = sorted({r.model for r in ok})
    palette = plt.cm.tab10.colors if len(models) <= 10 else plt.cm.tab20.colors
    color_map = {m: palette[i % len(palette)] for i, m in enumerate(models)}

    fig, axes = plt.subplots(
        2,
        1,
        figsize=(14, 8),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1]},
    )
    ax_scatter, ax_model = axes

    # ── top panel: TTLT scatter ──────────────────────────────────────────
    for model in models:
        pts = [(r.t_start - t0, r.ttlt_ms) for r in ok if r.model == model]
        if not pts:
            continue
        xs, ys = zip(*pts)
        ax_scatter.scatter(
            xs,
            ys,
            color=color_map[model],
            label=model.split("/")[-1],
            alpha=0.8,
            s=35,
            edgecolors="none",
            zorder=3,
        )

    # optional: also show TTFT as faint crosses
    ok_ttft = [r for r in ok if r.ttft_ms is not None]
    for model in models:
        pts = [(r.t_start - t0, r.ttft_ms) for r in ok_ttft if r.model == model]
        if not pts:
            continue
        xs, ys = zip(*pts)
        ax_scatter.scatter(
            xs,
            ys,
            color=color_map[model],
            marker="+",
            alpha=0.35,
            s=25,
            linewidths=0.8,
            zorder=2,
        )

    ax_scatter.set_ylabel("Latency (ms)")
    ax_scatter.set_title("Model-Switching Timeline  (● TTLT  + TTFT)")
    ax_scatter.legend(
        title="Model",
        fontsize=8,
        title_fontsize=8,
        loc="upper right",
        framealpha=0.8,
    )
    ax_scatter.grid(True, alpha=0.25)

    # ── bottom panel: which model was active at each request ─────────────
    model_indices = {m: i for i, m in enumerate(models)}
    xs_all = [r.t_start - t0 for r in ok]
    ys_all = [model_indices[r.model] for r in ok]
    colors_all = [color_map[r.model] for r in ok]

    ax_model.scatter(xs_all, ys_all, c=colors_all, s=20, alpha=0.9, edgecolors="none")
    ax_model.set_yticks(range(len(models)))
    ax_model.set_yticklabels([m.split("/")[-1] for m in models], fontsize=7)
    ax_model.set_xlabel("Elapsed time (s)")
    ax_model.set_ylabel("Model")
    ax_model.grid(True, alpha=0.2, axis="x")

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def generate_charts(out_dir: Path, results: list[RequestResult], tracker, t0: float) -> None:
    if not _PLOT:
        print("  [charts] matplotlib/numpy not available — skipping.")
        return
    ok = [r for r in results if r.success]
    _dist_chart(
        [r.ttft_ms for r in ok if r.ttft_ms is not None], "TTFT Distribution", "TTFT (ms)", out_dir / "chart_ttft.png"
    )
    _dist_chart(
        [r.ttlt_ms for r in ok if r.ttlt_ms is not None], "TTLT Distribution", "TTLT (ms)", out_dir / "chart_ttlt.png"
    )
    energy = [r.energy_j for r in ok if r.energy_j is not None]
    if energy:
        _dist_chart(energy, "Energy per Request", "Energy (J)", out_dir / "chart_energy_per_request.png")
        _dist_chart(
            [r.energy_per_token_mj for r in ok if r.energy_per_token_mj is not None],
            "Energy per Output Token",
            "Energy (mJ/token)",
            out_dir / "chart_energy_per_token.png",
        )
    _power_timeline(tracker.power_samples(), results, t0, out_dir / "chart_power_timeline.png")
    _scatter_energy_ttlt(results, out_dir / "chart_energy_vs_ttlt.png")
    _per_model_chart(results, "ttft_ms", "TTFT (ms)", out_dir / "chart_ttft_by_model.png")
    _per_model_chart(results, "energy_j", "Energy (J)", out_dir / "chart_energy_by_model.png")
    _model_switching_chart(results, t0, out_dir / "chart_model_switching.png")
    print(f"  [charts] Written to {out_dir}")


# ── CLI ───────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Benchmark Logos (or Ollama): TTFT, TTLT, GPU energy per request.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    p.add_argument(
        "--scenario",
        default="logos-sleep",
        choices=["logos-sleep", "logos-nosleep", "ollama"],
        help=(
            "logos-sleep:   Send to Logos; sleep mode enabled server-side. "
            "logos-nosleep: Send to Logos; sleep mode disabled server-side. "
            "ollama:        Send directly to Ollama (no logos_key; model names "
            "translated via benchmark_config.py)."
        ),
    )

    # Workload source
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--workload", type=Path, metavar="CSV", help="Workload CSV from prepare_benchmark.py.")
    src.add_argument("--prompts", type=Path, metavar="TXT", help="Plain-text file with one prompt per line.")

    # Connection
    p.add_argument("--logos-url", default="http://localhost:8080", help="Base URL of Logos or Ollama server.")
    p.add_argument(
        "--logos-key", default=None, help="Logos API key. Required for logos-sleep and logos-nosleep scenarios."
    )

    # Prompt-mode extras
    p.add_argument("--model", default="", help="Model name (overrides workload CSV body; required with --prompts).")
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument(
        "--interval-ms", type=float, default=0.0, help="Arrival offset between prompts in ms (--prompts mode)."
    )

    # ── GPU source: remote (default) or local ────────────────────────────
    gpu_grp = p.add_argument_group(
        "GPU energy measurement",
        "Use --gpu-host to measure energy on remote vLLM nodes via SSH (typical setup). "
        "Use --gpu-indices when the GPU is local (e.g. direct Ollama on this machine).",
    )
    gpu_excl = gpu_grp.add_mutually_exclusive_group()
    gpu_excl.add_argument(
        "--gpu-host",
        nargs="+",
        metavar="HOST",
        help="Hostnames/IPs of the GPU nodes running vLLM. " "The NVML poller is launched on each node via SSH.",
    )
    gpu_excl.add_argument(
        "--gpu-indices",
        type=int,
        nargs="+",
        default=None,
        metavar="IDX",
        help="Local NVML GPU device indices (only when GPU is on this machine).",
    )
    gpu_grp.add_argument("--gpu-ssh-user", default=None, help="SSH username for GPU nodes (default: current user).")
    gpu_grp.add_argument("--gpu-ssh-key", default=None, metavar="PATH", help="Path to SSH private key for GPU nodes.")
    gpu_grp.add_argument("--gpu-ssh-port", type=int, default=22, help="SSH port on GPU nodes.")
    gpu_grp.add_argument(
        "--gpu-device-index", type=int, default=0, help="GPU device index on each remote node (passed to NVML)."
    )
    gpu_grp.add_argument("--poll-interval-ms", type=float, default=100.0, help="GPU power-poll interval (ms).")

    # Concurrency / timing
    p.add_argument(
        "--sequential",
        action="store_true",
        help="Send one request at a time (ignores arrival offsets). " "Cleanest per-request energy attribution.",
    )
    p.add_argument("--max-concurrent", type=int, default=64)
    p.add_argument("--request-timeout-s", type=float, default=600.0)

    # Output
    p.add_argument("--output-dir", type=Path, default=Path("benchmark_results"))

    return p


async def _async_main(args: argparse.Namespace) -> None:
    # ── Validate ──────────────────────────────────────────────────────────
    if args.scenario != "ollama" and not args.logos_key:
        print(f"Error: --logos-key is required for scenario '{args.scenario}'.", file=sys.stderr)
        sys.exit(1)

    # ── Load workload ─────────────────────────────────────────────────────
    if args.workload:
        workload = _load_csv(args.workload, model_override=args.model or None)
        workload_name = args.workload.stem
    else:
        if not args.model:
            print("Error: --model is required when using --prompts.", file=sys.stderr)
            sys.exit(1)
        workload = _load_prompts(args.prompts, args.model, args.max_tokens, args.interval_ms)
        workload_name = args.prompts.stem

    # ── Load model map for Ollama scenario ────────────────────────────────
    model_map: dict[str, str] = {}
    if args.scenario == "ollama":
        model_map = _load_config_attr("OLLAMA_MODEL_MAP", {})
        if model_map:
            print(f"  [config] Loaded OLLAMA_MODEL_MAP ({len(model_map)} entries).")

    mode_str = "sequential" if args.sequential else f"concurrent (max {args.max_concurrent})"
    print(f"Scenario : {args.scenario}")
    print(f"Workload : {len(workload)} request(s) from '{workload_name}'")
    print(f"Target   : {args.logos_url}")
    print(f"Mode     : {mode_str}")

    # ── Build tracker ─────────────────────────────────────────────────────
    if args.gpu_host:
        import getpass

        ssh_user = args.gpu_ssh_user or getpass.getuser()
        print(f"GPU      : remote SSH → {args.gpu_host}  user={ssh_user}  device={args.gpu_device_index}")
        tracker = RemoteGPUTracker(
            hosts=args.gpu_host,
            ssh_user=ssh_user,
            ssh_key_path=args.gpu_ssh_key,
            ssh_port=args.gpu_ssh_port,
            gpu_index=args.gpu_device_index,
            poll_interval_ms=args.poll_interval_ms,
        )
    else:
        indices = args.gpu_indices if args.gpu_indices is not None else [0]
        print(f"GPU      : local NVML  indices={indices}")
        tracker = GPUTracker(indices, args.poll_interval_ms)

    tracker.start()

    # ── Run ───────────────────────────────────────────────────────────────
    print("\nRunning...")
    t_run_start = time.monotonic()

    if args.sequential:
        results = await run_sequential(
            workload,
            args.logos_url,
            args.logos_key,
            tracker,
            args.request_timeout_s,
            args.scenario,
            model_map,
        )
    else:
        results = await run_concurrent(
            workload,
            args.logos_url,
            args.logos_key,
            tracker,
            args.request_timeout_s,
            args.max_concurrent,
            args.scenario,
            model_map,
        )

    t_run_end = time.monotonic()
    tracker.stop()
    wall_s = t_run_end - t_run_start

    # ── Write outputs ─────────────────────────────────────────────────────
    summary = compute_summary(results, args.scenario, tracker.method)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.output_dir / f"{ts}_{args.scenario}_{workload_name}"
    out_dir.mkdir(parents=True, exist_ok=True)

    write_detailed(out_dir / "results_detailed.csv", results)
    write_summary(out_dir / "results_summary.csv", summary)
    generate_charts(out_dir, results, tracker, t_run_start)

    gpu_info = (
        {
            "hosts": args.gpu_host,
            "device_index": args.gpu_device_index,
            "ssh_user": (args.gpu_ssh_user or ""),
            "ssh_port": args.gpu_ssh_port,
        }
        if args.gpu_host
        else {"local_indices": args.gpu_indices or [0]}
    )
    (out_dir / "run_meta.json").write_text(
        json.dumps(
            {
                "scenario": args.scenario,
                "logos_url": args.logos_url,
                "workload": str(args.workload or args.prompts),
                "mode": mode_str,
                "gpu": gpu_info,
                "poll_interval_ms": args.poll_interval_ms,
                "energy_method": tracker.method,
                "total_wall_time_s": round(wall_s, 3),
                "request_count": len(results),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # ── Summary ───────────────────────────────────────────────────────────
    ok = summary["successful_requests"]
    fail = summary["failed_requests"]
    print(f"\n{'='*58}")
    print(f"  Scenario : {args.scenario}")
    print(f"  Wall time: {wall_s:.1f}s")
    print(f"  Requests : {summary['total_requests']} total  {ok} ok  {fail} failed")

    def _row(label: str, prefix: str, unit: str) -> None:
        mean = summary.get(f"{prefix}_mean", math.nan)
        p50 = summary.get(f"{prefix}_p50", math.nan)
        p95 = summary.get(f"{prefix}_p95", math.nan)
        if math.isnan(mean):
            return
        print(f"  {label:<14}: mean={mean:>8.1f}  p50={p50:>8.1f}  p95={p95:>8.1f}  ({unit})")

    _row("TTFT", "ttft_ms", "ms")
    _row("TTLT", "ttlt_ms", "ms")
    _row("TPOT", "tpot_ms", "ms/tok")

    if not math.isnan(summary.get("energy_j_mean", math.nan)):
        _row("Energy/req", "energy_j", "J")
        _row("Energy/tok", "energy_per_token_mj", "mJ/tok")
        total_e = summary.get("total_energy_j", math.nan)
        if not math.isnan(total_e):
            print(f"  Total GPU energy (sum of per-request windows): {total_e:.2f} J")
    else:
        print("  Energy   : not measured (GPU tracker unavailable)")

    print(f"  Results  : {out_dir}")
    print(f"{'='*58}")


def main() -> None:
    args = _build_parser().parse_args()
    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()

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
    pip install httpx numpy matplotlib
    # SSH uses the system 'ssh' binary — no extra library needed

Requirements (on each GPU node):
    nvidia-smi is used automatically (always available on NVIDIA systems).
    Optionally: pip install nvidia-ml-py  (enables hardware energy counter)

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
import csv
import importlib.util
import json
import math
import random
import shlex
import subprocess
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
    import matplotlib
    import numpy as np

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _PLOT = True
except ImportError:
    _PLOT = False


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


# ── SSH GPU Tracker (nvidia-smi via persistent SSH) ────────────────────────


def _find_root_ssh_key() -> Optional[str]:
    """Auto-detect the first available private key in /root/.ssh/."""
    for name in ("id_ed25519", "id_rsa", "id_ecdsa"):
        p = Path("/root/.ssh") / name
        if p.exists():
            return str(p)
    return None


class SshGpuTracker:
    """
    GPU power tracking via a persistent SSH connection to each GPU node.
    Runs 'nvidia-smi' in a loop remotely — no extra software needed on the node.

    Connects as 'logos-server' using the private key from /root/.ssh/.
    This mirrors exactly what 'ssh deimama' does from the logos-test root shell.
    """

    def __init__(
        self,
        hosts: list[str],
        ssh_user: str,
        ssh_key: Optional[str],
        poll_interval_ms: float,
    ):
        self._hosts = hosts
        self._ssh_user = ssh_user
        self._ssh_key = ssh_key
        self._poll_s = poll_interval_ms / 1000.0
        self._host_samples: list[list[tuple[float, float]]] = []  # (mono_t, power_mw)
        self._locks: list[threading.Lock] = []
        self._procs: list[subprocess.Popen] = []
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._launched_hosts: list[str] = []
        self.available = False
        self._use_counter = False
        self.method = "none"

    def _ssh_cmd(self, host: str, remote: str) -> str:
        parts = ["ssh"]
        if self._ssh_key:
            parts += ["-i", shlex.quote(self._ssh_key)]
        parts.append(f"{self._ssh_user}@{host}")
        parts.append(shlex.quote(remote))
        return " ".join(parts)

    def start(self) -> None:
        # Query all GPUs, sum their power with awk → one value per cycle.
        remote_loop = (
            f"while true; do "
            f"nvidia-smi --query-gpu=power.draw --format=csv,noheader,nounits 2>/dev/null"
            f" | awk '{{sum += $1}} END {{print sum+0}}'; "
            f"sleep {self._poll_s:.3f}; "
            f"done"
        )
        ok = 0
        for host in self._hosts:
            samples: list[tuple[float, float]] = []
            lock = threading.Lock()
            try:
                proc = subprocess.Popen(
                    self._ssh_cmd(host, remote_loop),
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                self._procs.append(proc)
                self._launched_hosts.append(host)
                self._host_samples.append(samples)
                self._locks.append(lock)
                t = threading.Thread(
                    target=self._reader,
                    args=(proc, samples, lock),
                    daemon=True,
                    name=f"gpu-ssh-{host}",
                )
                t.start()
                self._threads.append(t)
                ok += 1
            except Exception as exc:
                print(f"  [gpu] {host}: failed to launch — {exc}")

        if ok == 0:
            return

        # SSH handshake + first nvidia-smi can take >5s on a cold connection;
        # giving up too early silently disables energy measurement
        # (energy_method=none) even though the remote pollers keep running.
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if all(len(s) > 0 for s in self._host_samples):
                break
            time.sleep(0.05)

        for host, samples in zip(self._launched_hosts, self._host_samples):
            if samples:
                print(f"  [gpu] {host}: connected  power={samples[-1][1]/1000:.1f} W")
            else:
                print(f"  [gpu] {host}: connected  power=no data yet")

        connected = [h for h, s in zip(self._launched_hosts, self._host_samples) if s]
        if not connected:
            print("  [gpu] Warning: no data received from any host — check SSH access and nvidia-smi")
            return

        self.method = "polling"
        print(f"  [gpu] Energy: power-poll via nvidia-smi  " f"({self._poll_s*1000:.0f} ms, {len(connected)} host(s))")
        self.available = True

    def _reader(self, proc, samples, lock) -> None:
        for raw in proc.stdout:
            if self._stop.is_set():
                break
            try:
                p_w = float(raw.decode(errors="ignore").strip())
                with lock:
                    samples.append((time.monotonic(), p_w * 1000.0))
            except ValueError:
                continue  # skip [N/A] or empty lines

    def stop(self) -> None:
        self._stop.set()
        for proc in self._procs:
            try:
                proc.terminate()
            except Exception:
                pass

    def snapshot_energy_mj(self) -> Optional[float]:
        return None  # nvidia-smi has no cumulative energy counter

    def energy_from_counter(self, start_mj: float, end_mj: float) -> float:
        return (end_mj - start_mj) / 1000.0

    def energy_from_samples(self, t_start: float, t_end: float) -> Optional[float]:
        combined: list[tuple[float, float]] = []
        for samples, lock in zip(self._host_samples, self._locks):
            with lock:
                combined.extend((t, p) for t, p in samples if t_start <= t <= t_end)
        if len(combined) < 2:
            return None
        combined.sort()
        energy_j = 0.0
        for i in range(1, len(combined)):
            t0, p0 = combined[i - 1]
            t1, p1 = combined[i]
            energy_j += (p0 + p1) / 2.0 / 1000.0 * (t1 - t0)
        return energy_j

    def power_samples(self) -> list[tuple[float, float]]:
        combined: list[tuple[float, float]] = []
        for samples, lock in zip(self._host_samples, self._locks):
            with lock:
                combined.extend(samples)
        combined.sort()
        return combined


class _NullTracker:
    """Dummy tracker used during warmup — no energy measurement."""

    available = False
    _use_counter = False
    method = "none"

    def snapshot_energy_mj(self) -> None:
        return None

    def energy_from_counter(self, _start_mj: float, _end_mj: float) -> float:
        return 0.0

    def energy_from_samples(self, _t_start: float, _t_end: float) -> None:
        return None

    def power_samples(self) -> list:
        return []

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


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
    # Scheduler view at decision time, from Logos response headers
    # (X-Logos-Warmth-State / X-Logos-ETTFT-Ms); None for direct Ollama.
    # warmth_state: -1 = cold, 0 = warm but not running, 1+x = running with
    # x requests queued.
    warmth_state: Optional[int] = None
    ettft_ms: Optional[float] = None

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


def _parse_int_or_none(raw: Optional[str]) -> Optional[int]:
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _parse_float_or_none(raw: Optional[str]) -> Optional[float]:
    try:
        return float(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
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
        payload["cache_prompt"] = False  # disable Ollama prefix-caching for fair comparison
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
    warmth_state: Optional[int] = None
    ettft_ms: Optional[float] = None

    e_start = tracker.snapshot_energy_mj()
    t_start = time.monotonic()
    sent_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    try:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            status_code = resp.status_code
            warmth_state = _parse_int_or_none(resp.headers.get("x-logos-warmth-state"))
            ettft_ms = _parse_float_or_none(resp.headers.get("x-logos-ettft-ms"))

            if status_code >= 400:
                body = b""
                async for chunk in resp.aiter_bytes():
                    body += chunk
                error = body.decode(errors="ignore").strip()[:500] or f"HTTP {status_code}"
                t_end = time.monotonic()
                e_end = tracker.snapshot_energy_mj()
                received_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                ttlt_ms = (t_end - t_start) * 1000.0
                return RequestResult(
                    request_id=entry.request_id,
                    model=model,
                    mode=entry.mode,
                    priority=entry.priority,
                    status_code=status_code,
                    ttft_ms=None,
                    ttlt_ms=ttlt_ms,
                    energy_j=None,
                    prompt_tokens=None,
                    completion_tokens=None,
                    error=error,
                    t_start=t_start,
                    t_end=t_end,
                    sent_at=sent_at,
                    received_at=received_at,
                    scenario=scenario,
                    warmth_state=warmth_state,
                    ettft_ms=ettft_ms,
                )

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
                        delta = choice.get("delta", {})
                        # Trigger on any generated token:
                        #   "content"           — normal output (all backends)
                        #   "thinking"          — Ollama reasoning tokens (Qwen3, etc.)
                        #   "reasoning_content" — OpenAI / vLLM reasoning tokens
                        if delta.get("content") or delta.get("reasoning") or delta.get("reasoning_content"):
                            ttft_ms = (time.monotonic() - t_start) * 1000.0
                            first_token = True
                            break

                if usage := chunk.get("usage"):
                    prompt_tokens = usage.get("prompt_tokens")
                    completion_tokens = usage.get("completion_tokens")

    except Exception as exc:
        # httpx timeout exceptions stringify to "" — without the class name
        # the results CSV shows status_code=0 with an empty error column and
        # timeouts are indistinguishable from other transport failures.
        detail = str(exc).strip()
        error = (f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__)[:500]

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
        warmth_state=warmth_state,
        ettft_ms=ettft_ms,
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
    label_prefix: str = "",
) -> list[RequestResult]:
    results: list[RequestResult] = []
    n = len(workload)
    width = len(str(n))
    async with httpx.AsyncClient(timeout=timeout_s, verify=False) as client:
        for i, entry in enumerate(workload):
            print(
                f"  {label_prefix}[{i+1:{width}}/{n}] {entry.request_id} ... ",
                end="",
                flush=True,
            )
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

    async with httpx.AsyncClient(timeout=timeout_s, verify=False) as client:

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
                print(
                    f"  [{completed:{width}}/{n}] {r.request_id}  {_result_line(r)}",
                    flush=True,
                )

        start_mono = time.monotonic()
        await asyncio.gather(*[_run(e, start_mono) for e in workload])

    return results


async def run_burst(
    workload: list[WorkloadEntry],
    base_url: str,
    logos_key: Optional[str],
    tracker,
    timeout_s: float,
    scenario: str,
    model_map: dict[str, str],
    burst_size: int = 5,
    inter_burst_delay_s: float = 1.0,
    label_prefix: str = "",
) -> list[RequestResult]:
    """Send requests in batches of burst_size fully-concurrent requests.

    After each batch completes, waits inter_burst_delay_s before starting the next burst.
    """
    results: list[RequestResult] = []
    n = len(workload)
    width = len(str(n))
    done_counter = [0]
    lock = asyncio.Lock()

    async with httpx.AsyncClient(timeout=timeout_s, verify=False) as client:
        for batch_idx, batch_start in enumerate(range(0, n, burst_size)):
            if batch_idx > 0 and inter_burst_delay_s > 0:
                await asyncio.sleep(inter_burst_delay_s)
            batch = workload[batch_start : batch_start + burst_size]
            start_mono = time.monotonic()

            # Default-arg captures start_mono by value at definition time for this batch.
            async def _one(entry: WorkloadEntry, _sm: float = start_mono) -> None:
                r = await _dispatch(
                    client,
                    base_url,
                    logos_key,
                    entry,
                    _sm,
                    tracker,
                    sequential=False,
                    scenario=scenario,
                    model_map=model_map,
                )
                async with lock:
                    results.append(r)
                    done_counter[0] += 1
                    print(
                        f"  {label_prefix}[{done_counter[0]:{width}}/{n}]" f" {r.request_id}  {_result_line(r)}",
                        flush=True,
                    )

            await asyncio.gather(*[_one(e) for e in batch])

    return results


async def run_poisson(
    workload: list[WorkloadEntry],
    base_url: str,
    logos_key: Optional[str],
    tracker,
    timeout_s: float,
    scenario: str,
    model_map: dict[str, str],
    lam: float = 1.0,
    zeitraum_s: float = 1.0,
    label_prefix: str = "",
) -> list[RequestResult]:
    """Dispatch requests with Poisson-distributed inter-arrival times.

    lam events are expected per zeitraum_s seconds, giving a mean inter-arrival time of
    zeitraum_s / lam seconds.  Requests are launched independently and can overlap.
    """
    results: list[RequestResult] = []
    n = len(workload)
    width = len(str(n))
    done_counter = [0]
    lock = asyncio.Lock()
    rate = lam / zeitraum_s  # effective rate in req/s

    async with httpx.AsyncClient(timeout=timeout_s, verify=False) as client:
        start_mono = time.monotonic()

        async def _one(entry: WorkloadEntry) -> None:
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
                done_counter[0] += 1
                print(
                    f"  {label_prefix}[{done_counter[0]:{width}}/{n}]" f" {r.request_id}  {_result_line(r)}",
                    flush=True,
                )

        tasks: list[asyncio.Task] = []
        for i, entry in enumerate(workload):
            tasks.append(asyncio.create_task(_one(entry)))
            if i < n - 1:
                await asyncio.sleep(random.expovariate(rate))

        await asyncio.gather(*tasks)

    return results


async def run_mixed(
    workload: list[WorkloadEntry],
    base_url: str,
    logos_key: Optional[str],
    tracker,
    timeout_s: float,
    scenario: str,
    model_map: dict[str, str],
    burst_size: int = 5,
    inter_burst_delay_s: float = 1.0,
    lam: float = 1.0,
    zeitraum_s: float = 1.0,
) -> list[RequestResult]:
    """Split workload in thirds; run burst / Poisson / sequential all at once.

    All three sub-workloads start simultaneously so their traffic overlaps on the server.
    """
    n = len(workload)
    n_part = n // 3
    part_burst = workload[:n_part]
    part_poisson = workload[n_part : 2 * n_part]
    part_seq = workload[2 * n_part :]  # gets any remainder (up to +2 requests)

    r_burst, r_poisson, r_seq = await asyncio.gather(
        run_burst(
            part_burst,
            base_url,
            logos_key,
            tracker,
            timeout_s,
            scenario,
            model_map,
            burst_size=burst_size,
            inter_burst_delay_s=inter_burst_delay_s,
            label_prefix="[B]",
        ),
        run_poisson(
            part_poisson,
            base_url,
            logos_key,
            tracker,
            timeout_s,
            scenario,
            model_map,
            lam=lam,
            zeitraum_s=zeitraum_s,
            label_prefix="[P]",
        ),
        run_sequential(
            part_seq,
            base_url,
            logos_key,
            tracker,
            timeout_s,
            scenario,
            model_map,
            label_prefix="[S]",
        ),
    )
    return list(r_burst) + list(r_poisson) + list(r_seq)


# ── Warmup ────────────────────────────────────────────────────────────────


async def _warmup(
    base_url: str,
    logos_key: Optional[str],
    workload: list[WorkloadEntry],
    scenario: str,
    model_map: dict[str, str],
    timeout_s: float = 600.0,
) -> bool:
    """Send one short request per unique model, wait for all to finish.
    Returns True iff every warmup request succeeded."""
    models = list(dict.fromkeys(e.body["model"] for e in workload if e.body.get("model")))
    if not models:
        return True

    print(f"\nWarmup  : {len(models)} model(s) — waiting up to {timeout_s:.0f}s ...")
    null_tracker = _NullTracker()
    width = max(len(m) for m in models)

    entries: list[WorkloadEntry] = []
    for i, model in enumerate(models):
        template = next((e for e in workload if e.body.get("model") == model), workload[0])
        body = {
            **template.body,
            "model": model,
            "max_tokens": 16,
            "messages": [{"role": "user", "content": "Say OK."}],
        }
        entries.append(
            WorkloadEntry(
                request_id=f"warmup-{i+1:02d}",
                arrival_offset_ms=0.0,
                body=body,
                mode="interactive",
                priority="mid",
            )
        )

    async with httpx.AsyncClient(timeout=timeout_s + 5.0, verify=False) as client:
        tasks = [
            asyncio.create_task(
                _dispatch(
                    client,
                    base_url,
                    logos_key,
                    entry,
                    0.0,
                    null_tracker,
                    sequential=True,
                    scenario=scenario,
                    model_map=model_map,
                )
            )
            for entry in entries
        ]
        done, pending = await asyncio.wait(tasks, timeout=timeout_s)
        for task in pending:
            task.cancel()

        all_ok = True
        for model, task in zip(models, tasks):
            if task in done:
                try:
                    r = task.result()
                    if r.success:
                        ttft = f"TTFT={r.ttft_ms:.0f}ms" if r.ttft_ms else "no TTFT"
                        print(f"  [warmup] {model:<{width}}  OK      {ttft}")
                    else:
                        all_ok = False
                        msg = (r.error or "").replace("\n", " ").strip()
                        print(f"  [warmup] {model:<{width}}  FAIL    HTTP {r.status_code}")
                        if msg:
                            print(f"  [warmup] {' ' * width}    └─ {msg[:500]}")
                except Exception as exc:
                    all_ok = False
                    print(f"  [warmup] {model:<{width}}  ERROR   {exc}")
            else:
                all_ok = False
                print(f"  [warmup] {model:<{width}}  TIMEOUT")

    print("  [warmup] Done.")
    return all_ok


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
    "warmth_state",
    "ettft_ms",
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
                    "warmth_state": r.warmth_state if r.warmth_state is not None else "",
                    "ettft_ms": _f(r.ettft_ms),
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
    ax.hist(
        vals,
        bins=n_bins,
        density=True,
        alpha=0.6,
        color="#4C72B0",
        edgecolor="#1a3a6b",
        linewidth=0.4,
    )
    x = np.linspace(min(vals) * 0.9, max(vals) * 1.1, 400)
    ax.plot(x, _kde_curve(vals, x), color="#1a3a6b", linewidth=1.8)
    for p, col, lbl in [
        (50, "#2ca02c", "P50"),
        (95, "#d62728", "P95"),
        (99, "#9467bd", "P99"),
    ]:
        v = _pct(vals, p)
        ax.axvline(v, color=col, linestyle="--", linewidth=1.4, label=f"{lbl}: {v:.1f}")
    mean_v = sum(vals) / len(vals)
    ax.axvline(
        mean_v,
        color="#ff7f0e",
        linestyle=":",
        linewidth=1.6,
        label=f"Mean: {mean_v:.1f}",
    )
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
        [r.ttft_ms for r in ok if r.ttft_ms is not None],
        "TTFT Distribution",
        "TTFT (ms)",
        out_dir / "chart_ttft.png",
    )
    _dist_chart(
        [r.ttlt_ms for r in ok if r.ttlt_ms is not None],
        "TTLT Distribution",
        "TTLT (ms)",
        out_dir / "chart_ttlt.png",
    )
    energy = [r.energy_j for r in ok if r.energy_j is not None]
    if energy:
        _dist_chart(
            energy,
            "Energy per Request",
            "Energy (J)",
            out_dir / "chart_energy_per_request.png",
        )
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


# ── Service management ────────────────────────────────────────────────────


def _run_docker_compose(compose_args: list[str], cwd: Path, use_sudo: bool) -> None:
    prefix = ["sudo"] if use_sudo else []
    cmd = prefix + ["docker", "compose"] + compose_args
    print(f"  [logos] $ {' '.join(cmd)}  (cwd={cwd})")
    result = subprocess.run(cmd, cwd=str(cwd))
    if result.returncode != 0:
        raise RuntimeError(
            f"'docker compose {' '.join(compose_args)}' failed with exit code "
            f"{result.returncode}. Check the Docker output above for details."
        )


def _stop_logos(logos_dir: Path, use_sudo: bool) -> None:
    """Stop Logos via the root docker-compose (orchestrator + Traefik)."""
    _run_docker_compose(["down"], logos_dir, use_sudo)


def _start_logos(logos_dir: Path, use_sudo: bool) -> None:
    """Start Logos orchestrator via the local docker-compose."""
    # --no-recreate: never restart a container that is already running.
    # Without this, running from a different directory would cause Docker to
    # recreate Traefik with a different ./letsencrypt volume path, wiping the
    # Let's Encrypt certificate stored in acme.json.
    _run_docker_compose(["up", "-d", "--no-recreate"], logos_dir, use_sudo)


def _set_logos_sleep_mode_via_ssh(
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    workernode_dir: str,
    enabled: bool,
    use_sudo: bool = True,
) -> None:
    """Patch enable_sleep_mode in config.yml on each GPU node via SSH sed."""
    new_val = "true" if enabled else "false"
    config_file = f"{workernode_dir}/config.yml"
    # -E: extended regex, no backslash escaping needed for () and |
    # sudo is needed because sed -i writes a temp file in the same directory
    sudo = "sudo " if use_sudo else ""
    sed_expr = f"s/(^\\s*enable_sleep_mode:\\s*)(true|false)/\\1{new_val}/"
    remote_cmd = f"{sudo}sed -E -i '{sed_expr}' {shlex.quote(config_file)}"
    for host in hosts:
        parts = ["ssh", "-o", "StrictHostKeyChecking=no"]
        if ssh_key:
            parts += ["-i", ssh_key]
        parts += [f"{ssh_user}@{host}", remote_cmd]
        print(f"  [logos] {host}: Set enable_sleep_mode={new_val} in {config_file}")
        result = subprocess.run(parts)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to patch config on {host} (exit {result.returncode}).")


def _set_logos_poll_intervals_via_ssh(
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    workernode_dir: str,
    gpu_poll_interval: int,
    status_refresh_interval_seconds: int,
    use_sudo: bool = True,
) -> None:
    """Patch gpu_poll_interval (worker:) and status_refresh_interval_seconds (logos:) in config.yml.

    If a key is already present its value is replaced in-place. If the key is missing
    it is inserted as the first entry directly under the section header.
    Both workers need these values ≤ 1 so the model-state poller can record
    second-resolution deployment snapshots during the benchmark.
    """
    config_file = shlex.quote(f"{workernode_dir}/config.yml")
    sudo = "sudo " if use_sudo else ""

    patches = [
        ("worker", "gpu_poll_interval", gpu_poll_interval),
        ("logos", "status_refresh_interval_seconds", status_refresh_interval_seconds),
    ]
    for section, key, val in patches:
        # If key exists: replace integer value in-place with sed -E.
        # If key is missing: append it as the first child of the section header.
        remote_cmd = (
            f"if grep -qE '^[[:space:]]*{key}:' {config_file}; then "
            f"  {sudo}sed -E -i "
            f"'s/(^[[:space:]]*{key}:[[:space:]]*)[0-9]+/\\1{val}/' {config_file}; "
            f"else "
            f"  {sudo}sed -i '/^{section}:/a\\  {key}: {val}' {config_file}; "
            f"fi"
        )
        for host in hosts:
            parts = ["ssh", "-o", "StrictHostKeyChecking=no"]
            if ssh_key:
                parts += ["-i", ssh_key]
            parts += [f"{ssh_user}@{host}", remote_cmd]
            print(f"  [logos] {host}: Set {key}={val} in {workernode_dir}/config.yml")
            result = subprocess.run(parts)
            if result.returncode != 0:
                raise RuntimeError(f"Failed to patch {key} on {host} (exit {result.returncode}).")


def _stop_workernode_via_ssh(
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    workernode_dir: str,
    use_sudo: bool,
) -> None:
    """Stop the logos workernode on each GPU node via SSH docker compose down."""
    sudo = "sudo " if use_sudo else ""
    remote_cmd = f"cd {shlex.quote(workernode_dir)} && {sudo}docker compose down"
    for host in hosts:
        parts = ["ssh", "-o", "StrictHostKeyChecking=no"]
        if ssh_key:
            parts += ["-i", ssh_key]
        parts += [f"{ssh_user}@{host}", remote_cmd]
        print(f"  [logos] {host}: $ {remote_cmd}")
        result = subprocess.run(parts)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to stop workernode on {host} (exit {result.returncode}).")
        print(f"  [logos] {host}: workernode stopped.")


def _start_workernode_via_ssh(
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    workernode_dir: str,
    use_sudo: bool,
) -> None:
    """Start the logos workernode on each GPU node via SSH docker compose up -d."""
    sudo = "sudo " if use_sudo else ""
    remote_cmd = f"cd {shlex.quote(workernode_dir)} && {sudo}docker compose up -d"
    for host in hosts:
        parts = ["ssh", "-o", "StrictHostKeyChecking=no"]
        if ssh_key:
            parts += ["-i", ssh_key]
        parts += [f"{ssh_user}@{host}", remote_cmd]
        print(f"  [logos] {host}: $ {remote_cmd}")
        result = subprocess.run(parts)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to start workernode on {host} (exit {result.returncode}).")
        print(f"  [logos] {host}: workernode started.")


def _stop_logos_workernodes_if_running_via_ssh(
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    workernode_dir: str,
    use_sudo: bool,
) -> None:
    """Stop logos-workernode containers if any are running on the given hosts.

    Called before starting Ollama when --only-ollama is set, so the workernode
    doesn't hold GPU memory that Ollama needs. Safe to call even when the
    workernode directory does not exist on the host.
    """
    sudo = "sudo " if use_sudo else ""
    remote_cmd = (
        f"if [ -d {shlex.quote(workernode_dir)} ]; then "
        f"  cd {shlex.quote(workernode_dir)} && "
        f"  running=$({sudo}docker compose ps -q 2>/dev/null | tr -d '[:space:]') && "
        f'  if [ -n "$running" ]; then '
        f"    echo '[ollama] logos-workernode containers found — stopping ...'; "
        f"    {sudo}docker compose down; "
        f"  else "
        f"    echo '[ollama] No logos-workernode containers running.'; "
        f"  fi; "
        f"else "
        f"  echo '[ollama] Workernode dir not found — skipping workernode check.'; "
        f"fi"
    )
    for host in hosts:
        parts = ["ssh", "-o", "StrictHostKeyChecking=no"]
        if ssh_key:
            parts += ["-i", ssh_key]
        parts += [f"{ssh_user}@{host}", remote_cmd]
        print(f"  [ollama] {host}: Checking for running logos-workernode containers ...")
        subprocess.run(parts)  # non-fatal — best-effort only


async def _wait_for_tls(
    url: str,
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    timeout_s: float = 300.0,
) -> bool:
    """Wait until Traefik presents a valid TLS certificate, verified from a GPU node.

    Checking from a GPU node (not localhost) avoids hairpin-NAT issues on the
    logos server, and mirrors exactly the perspective of the workernode bridge.
    curl without -k exits non-zero on self-signed certs and zero on valid ones.
    """
    # curl exit codes relevant here:
    #   0  = success (cert valid)
    #   6  = DNS resolution failed
    #   7  = connection refused
    #   28 = timeout
    #   35 = SSL handshake failed
    #   60 = SSL cert verify failed (self-signed / expired)
    _CURL_EXIT_NAMES = {6: "DNS_FAIL", 7: "CONN_REFUSED", 28: "TIMEOUT", 35: "SSL_HANDSHAKE", 60: "CERT_VERIFY"}
    print(f"  [logos] Waiting for valid TLS certificate at {url} (up to {timeout_s:.0f}s) ...")
    host = hosts[0]
    deadline = time.monotonic() + timeout_s
    last_code: int = -1
    while time.monotonic() < deadline:
        parts = ["ssh", "-o", "StrictHostKeyChecking=no"]
        if ssh_key:
            parts += ["-i", ssh_key]
        parts += [f"{ssh_user}@{host}", f"curl -s --max-time 5 -o /dev/null -w '%{{http_code}}' {shlex.quote(url)}"]
        result = subprocess.run(parts, capture_output=True, text=True)
        if result.returncode == 0:
            print("  [logos] TLS certificate is valid.")
            return True
        if result.returncode != last_code:
            name = _CURL_EXIT_NAMES.get(result.returncode, f"exit {result.returncode}")
            print(f"  [logos] TLS not yet valid — curl {name} (retrying ...)")
            if result.returncode == 60:
                print("  [logos]   → Traefik is serving a self-signed certificate.")
                print("  [logos]   → Check: docker logs traefik 2>&1 | grep -i acme | tail -20")
                check_cmd = (
                    "cat /opt/logos/letsencrypt/acme.json | python3 -c"
                    ' "import json,sys; d=json.load(sys.stdin);'
                    " print(len((d.get('letsencrypt') or d.get('le',{})).get('Certificates') or []),"
                    " 'cert(s) in acme.json')\""
                )
                print(f"  [logos]   → Check: {check_cmd}")
            last_code = result.returncode
        await asyncio.sleep(5.0)
    print(f"  [logos] TIMEOUT — valid TLS certificate not available within {timeout_s:.0f}s.")
    return False


async def _wait_for_logos(
    url: str,
    timeout_s: float = 300.0,
    logos_key: Optional[str] = None,
) -> bool:
    """Poll Logos until the service is up AND at least one worker is connected.

    Phase 1 — service health: retry GET /v1/models until it returns a non-empty
    model list.  Fails immediately if the key has no permissions.

    Phase 2 — worker connectivity: send a minimal probe request to any model.
    The orchestrator returns 404 "No available model deployments" while workers
    are still booting / establishing their WebSocket session.  We keep retrying
    until we get any response other than that 404 (success, timeout, or a
    different error all indicate a worker is connected).  Model *loading* is NOT
    waited for — the benchmark warmup handles that.
    """
    print(f"  [logos] Waiting for service at {url} (up to {timeout_s:.0f}s) ...")
    deadline = time.monotonic() + timeout_s
    key_headers = {"logos_key": logos_key} if logos_key else {}

    # ── Phase 1: service health ───────────────────────────────────────────
    models: list = []
    while time.monotonic() < deadline:
        try:
            r = httpx.get(
                f"{url.rstrip('/')}/v1/models",
                headers=key_headers,
                timeout=5.0,
                verify=False,
            )
            if r.status_code == 200:
                models = r.json().get("data") or []
                if not models and logos_key:
                    _tls_host = url.split("://")[-1].split("/")[0].split(":")[0]
                    print(
                        "  [logos] ERROR: GET /v1/models returned an empty list.\n"
                        "  [logos]   The API key has no model permissions in the Logos DB.\n"
                        "  [logos]   Fix: use a logos_admin key, or add model + provider\n"
                        f"  [logos]   permissions via the admin UI at https://{_tls_host}:9443"
                    )
                    return False
                break  # service up, models visible
        except Exception:
            pass
        await asyncio.sleep(5.0)
    else:
        print(f"  [logos] TIMEOUT — service did not respond within {timeout_s:.0f}s.")
        return False

    print(f"  [logos] Service is ready. {len(models)} model(s) available:")
    for m in models:
        print(f"    • {m.get('id', '?')}")

    if not logos_key or not models:
        return True

    # ── Phase 2: worker connectivity ──────────────────────────────────────
    # Workers take a few seconds after container start to connect and register
    # their capabilities.  Until then every request returns 404 "No available
    # model deployments".  Pick any model and probe until we get a non-404
    # response — that proves a worker is in the registry (model loading can
    # still be in progress; the warmup handles that).
    probe_model = models[0]["id"]
    probe_payload = {
        "model": probe_model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
        "stream": False,
    }
    last_print = time.monotonic()
    print(f"  [logos] Waiting for workers to connect (probe: '{probe_model}') ...")
    while time.monotonic() < deadline:
        try:
            r = httpx.post(
                f"{url.rstrip('/')}/v1/chat/completions",
                json=probe_payload,
                headers={**key_headers, "Content-Type": "application/json"},
                timeout=10.0,
                verify=False,
            )
            # Any response other than "no available model deployments" means
            # at least one worker is registered — proceed to warmup.
            if r.status_code != 404:
                print("  [logos] Worker connected — starting warmup.")
                return True
            try:
                msg = (r.json().get("error") or {}).get("message", "")
            except Exception:
                msg = ""
            if "no available model deployments" not in msg.lower():
                print("  [logos] Worker connected — starting warmup.")
                return True
            # Still 404 "no available" → worker not in registry yet
            if time.monotonic() - last_print >= 10.0:
                print("  [logos]   Workers still connecting ...")
                last_print = time.monotonic()
        except httpx.TimeoutException:
            # Request took >10s → worker IS connected, model is loading
            print("  [logos] Worker connected (model loading) — starting warmup.")
            return True
        except Exception:
            pass
        await asyncio.sleep(3.0)

    print(f"  [logos] TIMEOUT — workers did not connect within {timeout_s:.0f}s.")
    return False


# ── Ollama service management ─────────────────────────────────────────────

_OLLAMA_DEFAULT_PORT = 11434
_OLLAMA_DEFAULT_MODELS_DIR = "/mnt/ceph/ollama_models"


def _ollama_compose_content(models_dir: str, local_models_dir: str) -> str:
    """Generate docker-compose.yml content for the Ollama benchmark container.

    Mounts models_dir as Ollama's model storage and the top-level shared
    filesystem (e.g. /mnt/ceph) read-only at the same path inside the
    container.  This means every host path returned by
    _find_model_local_path_via_ssh is valid inside the container without
    any translation, so 'FROM <host-path>' in a Modelfile works directly.
    """
    # Derive the shared-storage root to bind-mount (e.g. /mnt/ceph from
    # /mnt/ceph/.hf_cache/hub).  Take the first two non-root components.
    parts = Path(local_models_dir).parts  # ('/', 'mnt', 'ceph', ...)
    ceph_root = str(Path(*parts[:3])) if len(parts) >= 3 else str(Path(local_models_dir).parent)

    return f"""\
services:
  ollama:
    image: ollama/ollama:latest
    container_name: ollama-benchmark
    restart: "no"
    ports:
      - "{_OLLAMA_DEFAULT_PORT}:{_OLLAMA_DEFAULT_PORT}"
    volumes:
      - {models_dir}:/root/.ollama/models
      - {ceph_root}:{ceph_root}:ro
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
"""


def _deploy_ollama_compose_via_ssh(
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    compose_dir: str,
    use_sudo: bool,
    models_dir: str,
    local_models_dir: str,
) -> None:
    """Deploy docker-compose.yml for Ollama if not already present on the GPU node.

    Also ensures models_dir exists so Docker can bind-mount it without
    creating a root-owned directory on first run.
    """
    compose_file = f"{compose_dir}/docker-compose.yml"
    sudo = "sudo " if use_sudo else ""
    content = _ollama_compose_content(models_dir, local_models_dir)

    for host in hosts:
        ssh_base = ["ssh", "-o", "StrictHostKeyChecking=no"]
        if ssh_key:
            ssh_base += ["-i", ssh_key]

        # Check if compose file already exists
        check = subprocess.run(ssh_base + [f"{ssh_user}@{host}", f"test -f {shlex.quote(compose_file)}"])
        if check.returncode == 0:
            print(f"  [ollama] {host}: {compose_file} already present — skipping deploy.")
        else:
            print(f"  [ollama] {host}: Deploying docker-compose.yml to {compose_dir} ...")
            # Create directory and write file in one SSH round-trip via stdin pipe
            write_cmd = (
                f"{sudo}mkdir -p {shlex.quote(compose_dir)} && " f"{sudo}tee {shlex.quote(compose_file)} > /dev/null"
            )
            result = subprocess.run(
                ssh_base + [f"{ssh_user}@{host}", write_cmd],
                input=content.encode(),
            )
            if result.returncode != 0:
                raise RuntimeError(f"Failed to deploy docker-compose.yml to {host} (exit {result.returncode}).")
            print(f"  [ollama] {host}: docker-compose.yml deployed.")

        # Ensure the models directory exists (Docker bind-mount would create it
        # root-owned otherwise, causing permission issues for Ollama)
        mkdir_result = subprocess.run(ssh_base + [f"{ssh_user}@{host}", f"{sudo}mkdir -p {shlex.quote(models_dir)}"])
        if mkdir_result.returncode != 0:
            print(
                f"  [ollama] WARNING: Could not create {models_dir} on {host} — " "Docker will create it root-owned.",
                file=sys.stderr,
            )


def _start_ollama_docker_via_ssh(
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    compose_dir: str,
    use_sudo: bool,
) -> None:
    """Start the Ollama container via docker compose on each GPU node."""
    sudo = "sudo " if use_sudo else ""
    remote_cmd = f"cd {shlex.quote(compose_dir)} && {sudo}docker compose up -d"
    for host in hosts:
        parts = ["ssh", "-o", "StrictHostKeyChecking=no"]
        if ssh_key:
            parts += ["-i", ssh_key]
        parts += [f"{ssh_user}@{host}", remote_cmd]
        print(f"  [ollama] {host}: $ {remote_cmd}")
        result = subprocess.run(parts)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to start Ollama on {host} (exit {result.returncode}).")
        print(f"  [ollama] {host}: Ollama container started.")


def _stop_ollama_docker_via_ssh(
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    compose_dir: str,
    use_sudo: bool,
) -> None:
    """Stop and remove the Ollama container via docker compose on each GPU node."""
    sudo = "sudo " if use_sudo else ""
    remote_cmd = f"cd {shlex.quote(compose_dir)} && {sudo}docker compose down"
    for host in hosts:
        parts = ["ssh", "-o", "StrictHostKeyChecking=no"]
        if ssh_key:
            parts += ["-i", ssh_key]
        parts += [f"{ssh_user}@{host}", remote_cmd]
        print(f"  [ollama] {host}: $ {remote_cmd}")
        result = subprocess.run(parts)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to stop Ollama on {host} (exit {result.returncode}).")
        print(f"  [ollama] {host}: Ollama container stopped.")


def _open_ssh_tunnel(
    host: str,
    ssh_user: str,
    ssh_key: Optional[str],
    local_port: int,
    remote_port: int,
) -> "subprocess.Popen[bytes]":
    """Open an SSH local-port-forward tunnel in the background.

    Forwards localhost:<local_port> on this machine to localhost:<remote_port>
    on <host>.  Use this to reach a service on a remote node that is not
    directly reachable over the network (e.g. Ollama on a GPU node behind a
    firewall).

    Returns the Popen process; caller is responsible for terminating it.
    """
    parts = [
        "ssh",
        "-N",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "ExitOnForwardFailure=yes",
        "-L",
        f"{local_port}:localhost:{remote_port}",
    ]
    if ssh_key:
        parts += ["-i", ssh_key]
    parts += [f"{ssh_user}@{host}"]
    print(f"  [ollama] SSH tunnel: localhost:{local_port} → {host}:{remote_port}")
    return subprocess.Popen(parts)


def _close_ssh_tunnel(proc: "subprocess.Popen[bytes]") -> None:
    """Terminate an SSH tunnel process opened by _open_ssh_tunnel."""
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    print("  [ollama] SSH tunnel closed.")


async def _wait_for_ollama(url: str, timeout_s: float = 300.0) -> bool:
    """Wait until Ollama's /api/tags endpoint returns HTTP 200."""
    print(f"  [ollama] Waiting for Ollama at {url} (up to {timeout_s:.0f}s) ...")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{url.rstrip('/')}/api/tags", timeout=5.0)
            if r.status_code == 200:
                tags = r.json().get("models") or []
                print(f"  [ollama] Ready. {len(tags)} model(s) cached locally.")
                return True
        except Exception:
            pass
        await asyncio.sleep(3.0)
    print(f"  [ollama] TIMEOUT — Ollama did not respond within {timeout_s:.0f}s.")
    return False


async def _ensure_ollama_models(
    url: str,
    model_names: list[str],
    timeout_per_model_s: float = 600.0,
) -> None:
    """Pull each Ollama model via /api/pull if not already cached locally.

    Uses streaming NDJSON so progress is shown as it arrives.
    """
    if not model_names:
        return
    try:
        r = httpx.get(f"{url.rstrip('/')}/api/tags", timeout=10.0)
        cached = {m["name"] for m in (r.json().get("models") or [])} if r.status_code == 200 else set()
    except Exception:
        cached = set()

    for model in model_names:
        # Consider a model cached if any cached entry starts with its base name
        base = model.split(":")[0]
        if any(c == model or c.startswith(base + ":") for c in cached):
            print(f"  [ollama] '{model}' already cached — skipping pull.")
            continue
        print(f"  [ollama] Pulling '{model}' (this may take a while) ...")
        try:
            with httpx.stream(
                "POST",
                f"{url.rstrip('/')}/api/pull",
                json={"name": model, "stream": True},
                timeout=timeout_per_model_s,
            ) as resp:
                for line in resp.iter_lines():
                    try:
                        data = json.loads(line)
                        status = data.get("status", "")
                        if status:
                            print(f"  [ollama]   {model}: {status}        ", end="\r")
                    except Exception:
                        pass
            print(f"\n  [ollama] '{model}' pull complete.")
        except Exception as exc:
            print(f"\n  [ollama] WARNING: Failed to pull '{model}': {exc}", file=sys.stderr)


def _find_model_local_path_via_ssh(
    host: str,
    ssh_user: str,
    ssh_key: Optional[str],
    hf_model_name: str,
    base_dir: str,
) -> Optional[str]:
    """Find a usable local model path on a GPU node.

    Checks in order:
    1. HF Hub cache layout (primary): {base_dir}/models--{org}--{name}/snapshots/<latest>/
       This is the standard layout written by huggingface_hub / transformers.
       Path is used as-is with Ollama's 'FROM <dir>' directive.
    2. Flat HF directory: {base_dir}/{hf_model_name}/config.json exists.
    3. GGUF file inside the flat HF-named subdirectory.
    4. Broad find: any *.gguf under base_dir (max depth 5) matching the short name.

    Returns the first found path (directory or .gguf file), or None.
    """
    # HF Hub cache dir name: "google/gemma-3-4b-it" → "models--google--gemma-3-4b-it"
    cache_entry = "models--" + hf_model_name.replace("/", "--")
    snapshots_dir = f"{base_dir.rstrip('/')}/{cache_entry}/snapshots"
    hf_dir = f"{base_dir.rstrip('/')}/{hf_model_name}"
    short_name = hf_model_name.split("/")[-1].lower()

    remote_cmd = (
        # 1. Latest HF cache snapshot (most recent hash directory with config.json)
        f"_snaps={shlex.quote(snapshots_dir)}; "
        f'if [ -d "$_snaps" ]; then '
        f'  _h=$(ls -t "$_snaps" 2>/dev/null | head -1); '
        f'  if [ -n "$_h" ] && [ -f "$_snaps/$_h/config.json" ]; then '
        f'    echo "$_snaps/$_h"; exit 0; fi; fi; '
        # 2. Flat HF directory
        f"if [ -f {shlex.quote(hf_dir + '/config.json')} ]; then "
        f"echo {shlex.quote(hf_dir)}; exit 0; fi; "
        # 3. GGUF inside the flat HF-named subdirectory
        f"_g=$(ls {shlex.quote(hf_dir)}/*.gguf 2>/dev/null | head -1); "
        f'if [ -n "$_g" ]; then echo "$_g"; exit 0; fi; '
        # 4. Broad GGUF search
        f"find {shlex.quote(base_dir)} -maxdepth 5 -name '*.gguf' "
        f"2>/dev/null | grep -i {shlex.quote(short_name)} | head -1"
    )
    parts = ["ssh", "-o", "StrictHostKeyChecking=no"]
    if ssh_key:
        parts += ["-i", ssh_key]
    parts += [f"{ssh_user}@{host}", remote_cmd]
    result = subprocess.run(parts, capture_output=True, text=True)
    path = (result.stdout.strip().splitlines() or [""])[0].strip()
    return path or None


async def _import_ollama_models_from_disk(
    url: str,
    models: list[tuple[str, str]],
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    local_models_dir: str,
    timeout_s: float = 300.0,
) -> None:
    """Register Ollama models from local paths already on the GPU node.

    For each (ollama_name, hf_name) pair, searches under local_models_dir on
    the first GPU host.  When a HuggingFace directory or GGUF file is found the
    model is created via POST /api/create (streaming) so no download is needed.
    Models already in Ollama's registry are silently skipped.
    """
    if not models or not hosts:
        return

    try:
        r = httpx.get(f"{url.rstrip('/')}/api/tags", timeout=10.0)
        cached = {m["name"] for m in (r.json().get("models") or [])} if r.status_code == 200 else set()
    except Exception:
        cached = set()

    host = hosts[0]

    for ollama_name, hf_name in models:
        base = ollama_name.split(":")[0]
        if any(c == ollama_name or c.startswith(base + ":") for c in cached):
            print(f"  [ollama] '{ollama_name}': already registered — skipping local import.")
            continue
        if not hf_name:
            continue

        local_path = _find_model_local_path_via_ssh(host, ssh_user, ssh_key, hf_name, local_models_dir)
        if not local_path:
            print(f"  [ollama] '{ollama_name}': not found under {local_models_dir} — will try pull.")
            continue

        print(f"  [ollama] '{ollama_name}': importing from {local_path} ...")
        try:
            with httpx.stream(
                "POST",
                f"{url.rstrip('/')}/api/create",
                json={"name": ollama_name, "modelfile": f"FROM {local_path}\n", "stream": True},
                timeout=timeout_s,
            ) as resp:
                for line in resp.iter_lines():
                    try:
                        data = json.loads(line)
                        status = data.get("status", "")
                        if status:
                            print(f"  [ollama]   {ollama_name}: {status}        ", end="\r")
                    except Exception:
                        pass
            print(f"\n  [ollama] '{ollama_name}': import complete.")
        except Exception as exc:
            print(
                f"\n  [ollama] WARNING: disk-import of '{ollama_name}' failed: {exc} — will try pull.",
                file=sys.stderr,
            )


# ── Model deployment timeline ──────────────────────────────────────────────


@dataclass
class ModelStateSnapshot:
    t_offset_s: float
    provider_name: str
    model_name: str
    state: str  # running | sleeping | loaded | unloaded


async def _poll_model_states(
    logos_url: str,
    logos_key: str,
    t_start_mono: float,
    out: list,
    interval_s: float = 2.0,
) -> None:
    """Background task: cursor-poll POST /logosdb/get_ollama_vram_stats (second resolution)
    and record per-lane model states from scheduler_signals."""
    import datetime as _dt

    t_start_wall = time.time()
    url = f"{logos_url.rstrip('/')}/logosdb/get_ollama_vram_stats"
    req_headers = {"logos_key": logos_key, "Content-Type": "application/json"}

    async with httpx.AsyncClient(verify=False, timeout=httpx.Timeout(10.0)) as client:
        # Bootstrap cursor: record last_snapshot_id *before* benchmark data starts
        # so we only process snapshots produced during this run.
        last_snapshot_id = 0
        try:
            resp = await client.post(
                url,
                json={"resolution": "second", "after_snapshot_id": 0},
                headers=req_headers,
            )
            if resp.status_code == 200:
                last_snapshot_id = int(resp.json().get("last_snapshot_id") or 0)
        except Exception:
            pass

        while True:
            await asyncio.sleep(interval_s)
            try:
                resp = await client.post(
                    url,
                    json={"resolution": "second", "after_snapshot_id": last_snapshot_id},
                    headers=req_headers,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                new_cursor = data.get("last_snapshot_id")
                if new_cursor is not None:
                    last_snapshot_id = max(last_snapshot_id, int(new_cursor))

                for prov in data.get("providers") or []:
                    pname = prov.get("name") or prov.get("base_url") or "unknown"
                    for snap in prov.get("data") or []:
                        ts_str = snap.get("timestamp", "")
                        try:
                            ts = _dt.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            t_off = ts.timestamp() - t_start_wall
                        except Exception:
                            t_off = time.monotonic() - t_start_mono

                        lanes = (snap.get("scheduler_signals") or {}).get("lanes") or {}
                        for lane_info in lanes.values():
                            model_name = lane_info.get("model", "")
                            if not model_name:
                                continue
                            rt = lane_info.get("runtime_state") or ""
                            st = lane_info.get("sleep_state") or ""
                            if rt == "running":
                                state = "running"
                            elif rt == "sleeping" or st == "sleeping":
                                state = "sleeping"
                            elif rt in ("loaded", "starting"):
                                state = "loaded"
                            else:
                                state = "unloaded"
                            out.append(
                                ModelStateSnapshot(
                                    t_offset_s=t_off,
                                    provider_name=pname,
                                    model_name=model_name,
                                    state=state,
                                )
                            )
            except Exception:
                pass


def _write_model_timeline_csv(out_path: Path, snapshots: list) -> None:
    """Write model state time-series to CSV."""
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["t_offset_s", "provider", "model", "state"])
        w.writeheader()
        for s in snapshots:
            w.writerow(
                {
                    "t_offset_s": f"{s.t_offset_s:.3f}",
                    "provider": s.provider_name,
                    "model": s.model_name,
                    "state": s.state,
                }
            )


def _chart_model_timeline(
    out_path: Path,
    snapshots: list,
    t_total_s: float,
) -> None:
    """Gantt chart: per (node, model) a row of colored bars — green=running, blue=sleeping/loaded."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.patches as mpatches
        import matplotlib.pyplot as plt
    except ImportError:
        return

    if not snapshots:
        return

    from collections import defaultdict

    series: dict = defaultdict(list)
    for s in snapshots:
        series[(s.provider_name, s.model_name)].append(s)

    keys = sorted(series.keys())
    if not keys:
        return

    # State → color; "loaded" (idle, in VRAM) gets a lighter blue to distinguish from sleeping
    state_colors = {
        "running": "#2ca02c",  # green
        "sleeping": "#1f77b4",  # blue  (vLLM sleep mode: weights offloaded)
        "loaded": "#aec7e8",  # light blue (in VRAM but idle)
    }

    fig, ax = plt.subplots(figsize=(14, max(3.0, len(keys) * 0.7 + 1.5)))

    for row_idx, (pname, mname) in enumerate(keys):
        pts = sorted(series[(pname, mname)], key=lambda s: s.t_offset_s)
        i = 0
        while i < len(pts):
            state = pts[i].state
            color = state_colors.get(state)
            if color is None:
                i += 1
                continue
            # Extend run as long as state stays the same
            j = i + 1
            while j < len(pts) and pts[j].state == state:
                j += 1
            t_s = pts[i].t_offset_s
            # Bar extends to next known sample or end of benchmark
            t_e = pts[j].t_offset_s if j < len(pts) else t_total_s
            ax.barh(row_idx, max(0.01, t_e - t_s), left=t_s, height=0.6, color=color, edgecolor="none")
            i = j

    short_labels = [f"{p}\n{m.split('/')[-1]}" for p, m in keys]
    ax.set_yticks(range(len(keys)))
    ax.set_yticklabels(short_labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Time (s from benchmark start)")
    ax.set_xlim(0, t_total_s)
    ax.set_title("Model Deployment Timeline")

    legend_patches = [
        mpatches.Patch(color=state_colors["running"], label="Running"),
        mpatches.Patch(color=state_colors["sleeping"], label="Sleeping (VRAM freed)"),
        mpatches.Patch(color=state_colors["loaded"], label="Loaded (idle)"),
    ]
    ax.legend(handles=legend_patches, loc="lower right", fontsize=8)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  [timeline] chart written to {out_path.name}")


# ── Core benchmark execution ──────────────────────────────────────────────


async def _benchmark_scenario(
    scenario: str,
    base_url: str,
    logos_key: Optional[str],
    workload: list[WorkloadEntry],
    workload_name: str,
    model_map: dict[str, str],
    args: argparse.Namespace,
    traffic_pattern: str = "sequential",
    skip_warmup_override: bool = False,
) -> Optional[dict]:
    """
    Run one benchmark scenario with a single traffic pattern end-to-end.

    Builds a fresh GPU tracker, runs optional warmup, executes all requests,
    writes outputs (CSV + charts + run_meta.json), and prints a summary.
    Returns the summary dict, or None on critical failure.
    """
    burst_size: int = getattr(args, "burst_size", 5)
    inter_burst_delay_s: float = getattr(args, "burst_inter_delay", 1.0)
    poisson_lam: float = getattr(args, "poisson_lambda", 1.0)
    poisson_zeitraum_s: float = getattr(args, "poisson_zeitraum", 1.0)

    print(f"\nScenario : {scenario}")
    print(
        f"Pattern  : {traffic_pattern}  "
        f"(burst: size={burst_size}, gap={inter_burst_delay_s}s | "
        f"poisson: λ={poisson_lam}/{poisson_zeitraum_s}s)"
    )
    print(f"Workload : {len(workload)} request(s) from '{workload_name}'")
    print(f"Target   : {base_url}")

    if args.gpu_host:
        ssh_key = args.gpu_ssh_key or _find_root_ssh_key()
        print(
            f"GPU      : SSH nvidia-smi (all GPUs) → {args.gpu_host}  "
            f"user={args.gpu_ssh_user}  key={ssh_key or '(none)'}"
        )
        tracker = SshGpuTracker(
            hosts=args.gpu_host,
            ssh_user=args.gpu_ssh_user,
            ssh_key=ssh_key,
            poll_interval_ms=args.poll_interval_ms,
        )
    else:
        indices = args.gpu_indices if args.gpu_indices is not None else [0]
        print(f"GPU      : local NVML  indices={indices}")
        tracker = GPUTracker(indices, args.poll_interval_ms)

    tracker.start()

    if not (args.skip_warmup or skip_warmup_override):
        warmup_ok = await _warmup(
            base_url,
            logos_key,
            workload,
            scenario,
            model_map,
            timeout_s=args.warmup_timeout,
        )
        if not warmup_ok:
            print(
                "\nWarmup had failures (see above) — continuing anyway.",
                file=sys.stderr,
            )

    print("\nRunning...")
    t_run_start = time.monotonic()

    # Model-state polling runs concurrently with the benchmark (Logos scenarios only).
    # Requires status_refresh_interval_seconds: 1 on the workernode for 1s granularity.
    state_snapshots: list = []
    _poll_task: Optional[asyncio.Task] = None
    if logos_key is not None:
        _poll_task = asyncio.create_task(_poll_model_states(base_url, logos_key, t_run_start, state_snapshots))

    if traffic_pattern == "burst":
        results = await run_burst(
            workload,
            base_url,
            logos_key,
            tracker,
            args.request_timeout_s,
            scenario,
            model_map,
            burst_size=burst_size,
            inter_burst_delay_s=inter_burst_delay_s,
        )
    elif traffic_pattern == "poisson":
        results = await run_poisson(
            workload,
            base_url,
            logos_key,
            tracker,
            args.request_timeout_s,
            scenario,
            model_map,
            lam=poisson_lam,
            zeitraum_s=poisson_zeitraum_s,
        )
    elif traffic_pattern == "mixed":
        results = await run_mixed(
            workload,
            base_url,
            logos_key,
            tracker,
            args.request_timeout_s,
            scenario,
            model_map,
            burst_size=burst_size,
            inter_burst_delay_s=inter_burst_delay_s,
            lam=poisson_lam,
            zeitraum_s=poisson_zeitraum_s,
        )
    else:  # "sequential"
        results = await run_sequential(
            workload,
            base_url,
            logos_key,
            tracker,
            args.request_timeout_s,
            scenario,
            model_map,
        )

    t_run_end = time.monotonic()
    if _poll_task is not None:
        _poll_task.cancel()
        try:
            await _poll_task
        except asyncio.CancelledError:
            pass
    tracker.stop()
    wall_s = t_run_end - t_run_start

    summary = compute_summary(results, scenario, tracker.method)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.output_dir / f"{ts}_{scenario}_{workload_name}_{traffic_pattern}"
    out_dir.mkdir(parents=True, exist_ok=True)

    write_detailed(out_dir / "results_detailed.csv", results)
    write_summary(out_dir / "results_summary.csv", summary)
    generate_charts(out_dir, results, tracker, t_run_start)
    if state_snapshots:
        _write_model_timeline_csv(out_dir / "model_timeline.csv", state_snapshots)
        _chart_model_timeline(out_dir / "chart_model_timeline.png", state_snapshots, wall_s)

    gpu_info = (
        {"hosts": args.gpu_host, "ssh_user": (args.gpu_ssh_user or ""), "ssh_port": 22}
        if args.gpu_host
        else {"local_indices": args.gpu_indices or [0]}
    )
    (out_dir / "run_meta.json").write_text(
        json.dumps(
            {
                "scenario": scenario,
                "traffic_pattern": traffic_pattern,
                "burst_size": burst_size,
                "burst_inter_delay_s": inter_burst_delay_s,
                "poisson_lambda": poisson_lam,
                "poisson_zeitraum_s": poisson_zeitraum_s,
                "logos_url": base_url,
                "workload": str(args.workload or args.prompts),
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

    ok_count = summary["successful_requests"]
    fail_count = summary["failed_requests"]
    print(f"\n{'='*58}")
    print(f"  Scenario : {scenario}  [{traffic_pattern}]")
    print(f"  Wall time: {wall_s:.1f}s")
    print(f"  Requests : {summary['total_requests']} total  {ok_count} ok  {fail_count} failed")

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

    return summary


_TRAFFIC_PATTERNS = ["burst", "poisson", "sequential", "mixed"]


async def _run_all_traffic_patterns(
    scenario: str,
    base_url: str,
    logos_key: Optional[str],
    workload: list,
    workload_name: str,
    model_map: dict,
    args: argparse.Namespace,
) -> list:
    """Run all four traffic patterns for a scenario; warmup is done only for the first."""
    summaries = []
    for i, pattern in enumerate(_TRAFFIC_PATTERNS):
        print(f"\n{'─' * 58}")
        print(f"  Traffic pattern {i+1}/{len(_TRAFFIC_PATTERNS)}: {pattern.upper()}")
        print(f"{'─' * 58}")
        summary = await _benchmark_scenario(
            scenario,
            base_url,
            logos_key,
            workload,
            workload_name,
            model_map,
            args,
            traffic_pattern=pattern,
            skip_warmup_override=(i > 0),
        )
        summaries.append(summary)
    return summaries


# ── All-scenarios orchestrator ────────────────────────────────────────────


async def _async_run_all(args: argparse.Namespace) -> None:
    """Orchestrate logos-nosleep → ollama → logos-sleep, managing services between runs."""
    only_ollama: bool = getattr(args, "only_ollama", False)
    if not only_ollama and not args.logos_key:
        print("Error: --logos-key is required for --run-all-scenarios (unless --only-ollama).", file=sys.stderr)
        sys.exit(1)
    if not args.gpu_host:
        print("Error: --gpu-host is required for --run-all-scenarios.", file=sys.stderr)
        sys.exit(1)

    if args.workload:
        workload = _load_csv(args.workload, model_override=args.model or None)
        workload_name = args.workload.stem
    else:
        if not args.model:
            print("Error: --model is required when using --prompts.", file=sys.stderr)
            sys.exit(1)
        workload = _load_prompts(args.prompts, args.model, args.max_tokens, args.interval_ms)
        workload_name = args.prompts.stem

    ollama_model_map: dict[str, str] = _load_config_attr("OLLAMA_MODEL_MAP", {})
    if ollama_model_map:
        print(f"  [config] Loaded OLLAMA_MODEL_MAP ({len(ollama_model_map)} entries).")

    logos_url = args.logos_url
    # Default Ollama URL to the first GPU node on the standard Ollama port
    ollama_url = args.ollama_url or f"http://{args.gpu_host[0]}:{_OLLAMA_DEFAULT_PORT}"
    ollama_models_dir: str = getattr(args, "ollama_models_dir", _OLLAMA_DEFAULT_MODELS_DIR)
    ollama_local_models_dir: str = getattr(args, "ollama_local_models_dir", "/mnt/ceph/.hf_cache/hub")
    ollama_compose_dir: str = getattr(args, "ollama_compose_dir", "/opt/logos-ollama")
    logos_dir = args.logos_dir
    use_sudo = not args.no_sudo
    ssh_key = args.gpu_ssh_key or _find_root_ssh_key()
    # Defined early so _cleanup() can always reference them regardless of where
    # an abort occurs.
    ollama_host = args.gpu_host[:1]
    _tunnel_procs: list = []  # SSH port-forward processes opened during this run

    def _cleanup(reason: str = "cleanup") -> None:
        """Best-effort stop of all containers/tunnels started by this run.

        Called on KeyboardInterrupt, CancelledError, or any unhandled exception
        so that GPU nodes are never left with dangling containers after an abort.
        All sub-calls are wrapped individually — one failure won't skip the rest.
        """
        print(f"\n  [{reason}] Stopping all containers and closing tunnels ...", file=sys.stderr)
        for _p in list(_tunnel_procs):
            try:
                _close_ssh_tunnel(_p)
            except Exception:
                pass
        _tunnel_procs.clear()
        try:
            _stop_ollama_docker_via_ssh(ollama_host, args.gpu_ssh_user, ssh_key, ollama_compose_dir, use_sudo)
        except Exception as _exc:
            print(f"  [{reason}] WARNING (Ollama stop): {_exc}", file=sys.stderr)
        if getattr(args, "workernode_dir", None):
            try:
                _stop_workernode_via_ssh(args.gpu_host, args.gpu_ssh_user, ssh_key, args.workernode_dir, use_sudo)
            except Exception as _exc:
                print(f"  [{reason}] WARNING (workernode stop): {_exc}", file=sys.stderr)

    # Unique Ollama model names this workload needs (via model map)
    unique_workload_models = list(dict.fromkeys(e.body["model"] for e in workload if e.body.get("model")))
    ollama_models_needed = list(
        dict.fromkeys(ollama_model_map[m] for m in unique_workload_models if m in ollama_model_map)
    )
    # Reverse map: ollama_name → hf_name (used for local path search)
    ollama_to_hf_map = {v: k for k, v in ollama_model_map.items()}

    print(f"\n{'='*58}")
    if only_ollama:
        print("  All-scenarios benchmark — Ollama only")
    else:
        print("  All-scenarios benchmark")
        print("  Order: logos-nosleep → ollama → logos-sleep")
    print(f"  Logos URL      : {logos_url}")
    print(f"  Ollama URL     : {ollama_url}")
    print(f"  Ollama node    : {args.gpu_host[0]}  (single-node; Ollama has no multi-node support)")
    print(f"  Ollama compose : {ollama_compose_dir}/docker-compose.yml  (on GPU node)")
    print(f"  Ollama models  : {', '.join(ollama_models_needed) or '(none mapped)'}")
    print(f"  Ollama MODELS/ : {ollama_models_dir}")
    print(f"  Ollama HF src  : {ollama_local_models_dir}")
    if not only_ollama:
        print(f"  Config file    : {args.workernode_dir}/config.yml  (on each GPU node)")
        print(f"  Workernode dir : {args.workernode_dir}  (on {args.gpu_host})")
    print(f"  Workload       : {len(workload)} requests from '{workload_name}'")
    print(f"{'='*58}")

    try:
        if not only_ollama:
            # ── Step 0: ensure orchestrator + Traefik are running ─────────────
            # We never tear down the orchestrator between scenarios because that
            # would also restart Traefik and lose the valid Let's Encrypt cert.
            # Workernodes reconnect to the already-running orchestrator when restarted.
            print("\n[Step 0] Ensuring Logos orchestrator is running ...")
            _start_logos(logos_dir, use_sudo)  # docker compose up -d  (no-op if already running)
            # TLS check uses the admin entrypoint (port 9443): it is the only
            # entrypoint with a Host() rule in docker-compose, so Traefik always
            # serves the LE cert there. Workernodes also connect via 9443.
            _tls_host = logos_url.split("://")[-1].split("/")[0].split(":")[0]
            _tls_url = f"https://{_tls_host}:9443"
            if not await _wait_for_tls(_tls_url, args.gpu_host, args.gpu_ssh_user, ssh_key, timeout_s=300.0):
                print("  ERROR: Traefik did not obtain a valid TLS certificate — aborting.", file=sys.stderr)
                sys.exit(1)

            # ── Step 1: logos-nosleep ─────────────────────────────────────────
            print("\n" + "─" * 58)
            print("[Step 1/3] logos-nosleep")
            print("─" * 58)
            _set_logos_sleep_mode_via_ssh(
                args.gpu_host, args.gpu_ssh_user, ssh_key, args.workernode_dir, enabled=False, use_sudo=use_sudo
            )
            _set_logos_poll_intervals_via_ssh(
                args.gpu_host,
                args.gpu_ssh_user,
                ssh_key,
                args.workernode_dir,
                gpu_poll_interval=1,
                status_refresh_interval_seconds=1,
                use_sudo=use_sudo,
            )
            _stop_workernode_via_ssh(args.gpu_host, args.gpu_ssh_user, ssh_key, args.workernode_dir, use_sudo)
            _start_workernode_via_ssh(args.gpu_host, args.gpu_ssh_user, ssh_key, args.workernode_dir, use_sudo)
            if not await _wait_for_logos(logos_url, timeout_s=args.warmup_timeout, logos_key=args.logos_key):
                print("  ERROR: Logos did not start in time — aborting.", file=sys.stderr)
                sys.exit(1)
            await _run_all_traffic_patterns(
                "logos-nosleep", logos_url, args.logos_key, workload, workload_name, {}, args
            )
            print("\n  Stopping workernodes ...")
            _stop_workernode_via_ssh(args.gpu_host, args.gpu_ssh_user, ssh_key, args.workernode_dir, use_sudo)

        # ── Step 2: ollama ────────────────────────────────────────────────────
        step_label = "[Step 1/1] ollama" if only_ollama else "[Step 2/3] ollama"
        print("\n" + "─" * 58)
        print(step_label)
        print("─" * 58)
        # Ollama runs on one GPU node only — it has no native multi-node support.
        # This is intentional: the benchmark compares Logos (multi-node orchestration)
        # against Ollama (single-node baseline) to quantify the value of distribution.
        if only_ollama:
            # When running Ollama in isolation, make sure no logos-workernode
            # containers are occupying GPU memory on the target node.
            _stop_logos_workernodes_if_running_via_ssh(
                args.gpu_host,
                args.gpu_ssh_user,
                ssh_key,
                getattr(args, "workernode_dir", "/opt/logos-workernode"),
                use_sudo,
            )
        _deploy_ollama_compose_via_ssh(
            ollama_host,
            args.gpu_ssh_user,
            ssh_key,
            ollama_compose_dir,
            use_sudo,
            ollama_models_dir,
            ollama_local_models_dir,
        )
        _start_ollama_docker_via_ssh(ollama_host, args.gpu_ssh_user, ssh_key, ollama_compose_dir, use_sudo)

        # Port 11434 on the GPU node is typically not reachable directly from the
        # logos-test server (firewall).  Open an SSH local-port-forward so all
        # HTTP calls go through the existing SSH path instead.
        _ollama_host_part = ollama_url.split("://")[-1].split("/")[0]
        _ollama_port = int(_ollama_host_part.split(":")[-1]) if ":" in _ollama_host_part else _OLLAMA_DEFAULT_PORT
        tunnel_proc = _open_ssh_tunnel(
            ollama_host[0],
            args.gpu_ssh_user,
            ssh_key,
            local_port=_ollama_port,
            remote_port=_ollama_port,
        )
        _tunnel_procs.append(tunnel_proc)
        await asyncio.sleep(2.0)  # let the tunnel establish before the first HTTP probe
        tunnel_url = f"http://localhost:{_ollama_port}"

        try:
            if not await _wait_for_ollama(tunnel_url, timeout_s=args.warmup_timeout):
                print(
                    "  WARNING: Ollama did not become ready — skipping ollama scenario.",
                    file=sys.stderr,
                )
            else:
                await _import_ollama_models_from_disk(
                    tunnel_url,
                    [(n, ollama_to_hf_map.get(n, "")) for n in ollama_models_needed],
                    ollama_host,
                    args.gpu_ssh_user,
                    ssh_key,
                    local_models_dir=ollama_local_models_dir,
                    timeout_s=args.warmup_timeout,
                )
                await _ensure_ollama_models(tunnel_url, ollama_models_needed, timeout_per_model_s=args.warmup_timeout)
                await _run_all_traffic_patterns(
                    "ollama", tunnel_url, None, workload, workload_name, ollama_model_map, args
                )
        finally:
            # Always stop the Ollama container and close the tunnel, even on abort.
            _stop_ollama_docker_via_ssh(ollama_host, args.gpu_ssh_user, ssh_key, ollama_compose_dir, use_sudo)
            _close_ssh_tunnel(tunnel_proc)
            if tunnel_proc in _tunnel_procs:
                _tunnel_procs.remove(tunnel_proc)

        if not only_ollama:
            # ── Step 3: logos-sleep ───────────────────────────────────────────
            print("\n" + "─" * 58)
            print("[Step 3/3] logos-sleep")
            print("─" * 58)
            _set_logos_sleep_mode_via_ssh(
                args.gpu_host, args.gpu_ssh_user, ssh_key, args.workernode_dir, enabled=True, use_sudo=use_sudo
            )
            _set_logos_poll_intervals_via_ssh(
                args.gpu_host,
                args.gpu_ssh_user,
                ssh_key,
                args.workernode_dir,
                gpu_poll_interval=1,
                status_refresh_interval_seconds=1,
                use_sudo=use_sudo,
            )
            _start_workernode_via_ssh(args.gpu_host, args.gpu_ssh_user, ssh_key, args.workernode_dir, use_sudo)
            if not await _wait_for_logos(logos_url, timeout_s=args.warmup_timeout, logos_key=args.logos_key):
                print("  ERROR: Logos did not start in time — aborting.", file=sys.stderr)
                sys.exit(1)
            await _run_all_traffic_patterns("logos-sleep", logos_url, args.logos_key, workload, workload_name, {}, args)
            print("\n  Stopping workernodes ...")
            _stop_workernode_via_ssh(args.gpu_host, args.gpu_ssh_user, ssh_key, args.workernode_dir, use_sudo)

        print(f"\n{'='*58}")
        print("  All scenarios complete.")
        print(f"  Results written to: {args.output_dir}")
        print(f"{'='*58}")

    except (KeyboardInterrupt, asyncio.CancelledError):
        _cleanup("interrupt")
        print("  Benchmark aborted.", file=sys.stderr)
        raise
    except Exception:
        _cleanup("error")
        raise


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
    src.add_argument(
        "--workload",
        type=Path,
        metavar="CSV",
        help="Workload CSV from prepare_benchmark.py.",
    )
    src.add_argument(
        "--prompts",
        type=Path,
        metavar="TXT",
        help="Plain-text file with one prompt per line.",
    )

    # Connection
    p.add_argument(
        "--logos-url",
        default="http://localhost:8080",
        help="Base URL of Logos or Ollama server.",
    )
    p.add_argument(
        "--logos-key",
        default=None,
        help="Logos API key. Required for logos-sleep and logos-nosleep scenarios.",
    )

    # Prompt-mode extras
    p.add_argument(
        "--model",
        default="",
        help="Model name (overrides workload CSV body; required with --prompts).",
    )
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument(
        "--interval-ms",
        type=float,
        default=0.0,
        help="Arrival offset between prompts in ms (--prompts mode).",
    )

    # ── GPU energy measurement ────────────────────────────────────────────
    gpu_grp = p.add_argument_group(
        "GPU energy measurement",
        "SSHes into GPU nodes as 'logos-server' and polls nvidia-smi. "
        "Use --gpu-indices only when the GPU is local (e.g. direct Ollama on this machine).",
    )
    gpu_excl = gpu_grp.add_mutually_exclusive_group()
    gpu_excl.add_argument(
        "--gpu-host",
        nargs="+",
        metavar="HOST",
        help="SSH hostname(s) of GPU nodes, e.g. deimama hochbruegge.",
    )
    gpu_excl.add_argument(
        "--gpu-indices",
        type=int,
        nargs="+",
        default=None,
        metavar="IDX",
        help="Local NVML GPU device indices (only when GPU is on this machine).",
    )
    gpu_grp.add_argument("--gpu-ssh-user", default="logos-server", help="SSH username on GPU nodes.")
    gpu_grp.add_argument(
        "--gpu-ssh-key",
        default=None,
        metavar="PATH",
        help="SSH private key path (default: auto-detect from /root/.ssh/).",
    )
    gpu_grp.add_argument(
        "--poll-interval-ms",
        type=float,
        default=500.0,
        help="nvidia-smi poll interval in ms.",
    )

    # Warmup
    p.add_argument(
        "--warmup-timeout",
        type=float,
        default=1800.0,
        metavar="S",
        help="Seconds to wait for warmup responses before starting the benchmark. "
        "One request per unique model is sent concurrently. "
        "Cold-loading large models can take several minutes — keep this generous.",
    )
    p.add_argument("--skip-warmup", action="store_true", help="Skip the warmup phase.")

    # Concurrency / timing
    p.add_argument(
        "--sequential",
        action="store_true",
        help="(Legacy) Send one request at a time in the sequential traffic pattern.",
    )
    p.add_argument("--max-concurrent", type=int, default=64)
    p.add_argument("--request-timeout-s", type=float, default=600.0)

    # Traffic patterns
    tp_grp = p.add_argument_group(
        "Traffic patterns",
        "Each scenario is run 4× with different traffic shapes: " "burst, Poisson, sequential, and mixed.",
    )
    tp_grp.add_argument(
        "--burst-size",
        type=int,
        default=5,
        metavar="N",
        help="Größe eines Bursts: Anzahl gleichzeitiger Requests pro Burst. Default: 5.",
    )
    tp_grp.add_argument(
        "--burst-inter-delay",
        type=float,
        default=1.0,
        metavar="S",
        help="Zeitabstand zwischen Bursts in Sekunden. Default: 1.0.",
    )
    tp_grp.add_argument(
        "--poisson-lambda",
        type=float,
        default=1.0,
        metavar="λ",
        help="Höhe der Poisson-Verteilung: erwartete Requests pro --poisson-zeitraum. Default: 1.0.",
    )
    tp_grp.add_argument(
        "--poisson-zeitraum",
        type=float,
        default=1.0,
        metavar="S",
        help="Zeitraum in Sekunden für --poisson-lambda. "
        "Mittlere Inter-Arrival-Zeit = zeitraum / lambda. Default: 1.0.",
    )

    # Output
    p.add_argument("--output-dir", type=Path, default=Path("benchmark_results"))

    # ── All-scenarios orchestration ───────────────────────────────────────
    svc_grp = p.add_argument_group(
        "All-scenarios orchestration (--run-all-scenarios)",
        "Runs logos-nosleep → ollama → logos-sleep automatically, managing "
        "Docker Compose and config.yml between each scenario.",
    )
    svc_grp.add_argument(
        "--run-all-scenarios",
        action="store_true",
        help="Run all three scenarios in sequence (ignores --scenario).",
    )
    svc_grp.add_argument(
        "--logos-dir",
        type=Path,
        default=Path("/opt/logos"),
        metavar="DIR",
        help="Root Logos directory (contains docker-compose.yml with Traefik " "and logos-workernode/ subdirectory).",
    )
    svc_grp.add_argument(
        "--logos-config",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to logos-workernode/config.yml " "(default: <logos-dir>/logos-workernode/config.yml).",
    )
    svc_grp.add_argument(
        "--ollama-url",
        default=None,
        metavar="URL",
        help="Base URL for the Ollama server (default: same as --logos-url).",
    )
    svc_grp.add_argument(
        "--no-sudo",
        action="store_true",
        help="Omit 'sudo' from docker compose commands (default: sudo is prepended).",
    )
    svc_grp.add_argument(
        "--workernode-dir",
        default="/opt/logos-workernode",
        metavar="DIR",
        help="Directory on each GPU node where the workernode docker-compose.yml lives. "
        "Used by --run-all-scenarios to SSH in and run 'docker compose up -d'.",
    )
    svc_grp.add_argument(
        "--only-ollama",
        action="store_true",
        help="With --run-all-scenarios: run only the Ollama scenario (skip logos-nosleep "
        "and logos-sleep). Useful for testing Ollama without a full Logos setup. "
        "--logos-key is not required when this flag is set.",
    )
    svc_grp.add_argument(
        "--ollama-compose-dir",
        default="/opt/logos-ollama",
        metavar="DIR",
        help="Directory on the GPU node where the Ollama docker-compose.yml is stored. "
        "Created automatically if it does not exist. "
        "Default: /opt/logos-ollama",
    )
    svc_grp.add_argument(
        "--ollama-models-dir",
        default=_OLLAMA_DEFAULT_MODELS_DIR,
        metavar="DIR",
        help=f"Directory on the GPU nodes where Ollama stores downloaded models "
        f"(OLLAMA_MODELS env var). Default: {_OLLAMA_DEFAULT_MODELS_DIR}",
    )
    svc_grp.add_argument(
        "--ollama-local-models-dir",
        default="/mnt/ceph/.hf_cache/hub",
        metavar="DIR",
        help="Base directory on the GPU node to search for pre-existing models. "
        "Supports the standard HuggingFace Hub cache layout "
        "(models--<org>--<name>/snapshots/<hash>/) as well as flat HF directories "
        "and GGUF files. Ollama imports any model found here instead of downloading it. "
        "Default: /mnt/ceph/.hf_cache/hub",
    )

    return p


async def _async_main(args: argparse.Namespace) -> None:
    # ── Validate ──────────────────────────────────────────────────────────
    if args.scenario != "ollama" and not args.logos_key:
        print(
            f"Error: --logos-key is required for scenario '{args.scenario}'.",
            file=sys.stderr,
        )
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

    # ── Run all traffic patterns ───────────────────────────────────────────
    await _run_all_traffic_patterns(
        args.scenario,
        args.logos_url,
        args.logos_key,
        workload,
        workload_name,
        model_map,
        args,
    )


def main() -> None:
    args = _build_parser().parse_args()
    if args.run_all_scenarios:
        asyncio.run(_async_run_all(args))
    else:
        asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()

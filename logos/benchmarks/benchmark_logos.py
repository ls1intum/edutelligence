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
import getpass
import importlib.util
import json
import math
import os
import random
import shlex
import socket
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


try:
    import yaml as _yaml

    _YAML = True
except ImportError:
    _YAML = False


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


def _build_ssh_cmd(
    host: str,
    ssh_user: str,
    ssh_key: Optional[str],
    remote_cmd: str,
    relay_host: Optional[str] = None,
    relay_user: Optional[str] = None,
) -> list[str]:
    """Build SSH command list to execute remote_cmd on host.

    When relay_host is set, routes via nested SSH so the relay's key is used
    for the final hop (Mac → relay → host). This allows running the benchmark
    from a developer machine that only has key access to the relay (logos-test),
    while logos-test itself holds the key authorized on the GPU nodes.
    """
    if relay_host:
        outer = ["ssh", "-o", "StrictHostKeyChecking=no"]
        if ssh_key:
            outer += ["-i", ssh_key]
        outer.append(f"{relay_user}@{relay_host}")
        inner = f"sudo ssh -o StrictHostKeyChecking=no {shlex.quote(ssh_user + '@' + host)} {shlex.quote(remote_cmd)}"
        outer.append(inner)
        return outer
    parts = ["ssh", "-o", "StrictHostKeyChecking=no"]
    if ssh_key:
        parts += ["-i", ssh_key]
    parts += [f"{ssh_user}@{host}", remote_cmd]
    return parts


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
        relay_host: Optional[str] = None,
        relay_user: Optional[str] = None,
    ):
        self._hosts = hosts
        self._ssh_user = ssh_user
        self._ssh_key = ssh_key
        self._poll_s = poll_interval_ms / 1000.0
        self._relay_host = relay_host
        self._relay_user = relay_user
        self._host_samples: list[list[tuple[float, float]]] = []  # (mono_t, power_mw)
        self._locks: list[threading.Lock] = []
        self._procs: list[subprocess.Popen] = []
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._launched_hosts: list[str] = []
        self.available = False
        self._use_counter = False
        self.method = "none"

    def _ssh_cmd(self, host: str, remote: str) -> list[str]:
        return _build_ssh_cmd(host, self._ssh_user, self._ssh_key, remote, self._relay_host, self._relay_user)

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
                    shell=False,
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


class ShellyTracker:
    """
    Wall-power monitoring via Shelly Plug M Gen 3 devices.

    shelly_daemon.py runs persistently on the Raspberry Pi and pushes power
    readings to logos-test every second. This tracker binds a local port and
    collects those readings — no SSH needed.

    Each reading is JSON: {"deimama": W, "deipapa": W, "total": W}

    Three transports are supported (must match the daemon's):
      udp  — datagram push (default; simplest, but campus firewalls often drop
             inter-subnet UDP).
      tcp  — newline-delimited JSON over a persistent TCP connection; use this
             when UDP is filtered between the Pi and the benchmark host.
      http — readings arrive as HTTPS POSTs through Traefik (port 443) to a
             pipeline-managed ingest sidecar that appends them to a local
             newline-delimited file; this tracker tails that file. Use when only
             443 passes the firewall. See _start_shelly_ingest_sidecar().

    Implements the same interface as SshGpuTracker so it is a drop-in energy
    tracker. Measures total wall power (GPU + CPU + RAM + ...) which is more
    complete than nvidia-smi GPU-only readings.
    """

    def __init__(self, port: int = 9876, transport: str = "udp", ingest_file: Optional[str] = None):
        self._port = port
        self._transport = transport.lower()
        self._ingest_file = ingest_file
        self._samples: list[tuple[float, float]] = []  # (mono_t, total_mw)
        self._lock = threading.Lock()
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.available = False
        self._use_counter = False
        self.method = "none"

    def start(self) -> None:
        if self._transport == "http":
            if not self._ingest_file:
                print("  [shelly] http transport requires an ingest file path — disabled.")
                return
            self._thread = threading.Thread(target=self._reader_http, daemon=True, name="shelly-http")
            self._thread.start()
        else:
            is_tcp = self._transport == "tcp"
            sock_type = socket.SOCK_STREAM if is_tcp else socket.SOCK_DGRAM
            self._sock = socket.socket(socket.AF_INET, sock_type)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self._sock.bind(("", self._port))
                if is_tcp:
                    self._sock.listen(4)
                self._sock.settimeout(1.0)
            except OSError as exc:
                print(f"  [shelly] bind to :{self._port} failed: {exc}")
                self._sock.close()
                self._sock = None
                return

            reader = self._reader_tcp if is_tcp else self._reader_udp
            self._thread = threading.Thread(target=reader, daemon=True, name=f"shelly-{self._transport}")
            self._thread.start()

        # Wait up to 5s for the first reading from the always-running daemon
        # (TCP needs a moment to accept the connection + first line).
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            with self._lock:
                if self._samples:
                    break
            time.sleep(0.1)

        with self._lock:
            if not self._samples:
                print(
                    f"  [shelly] Warning: no {self._transport.upper()} readings on :{self._port} "
                    f"— is shelly_daemon.py running (transport={self._transport}) and reachable?"
                )
                return
            total_w = self._samples[-1][1] / 1000.0

        self.method = f"shelly-{self._transport}"
        self.available = True
        print(f"  [shelly] Receiving on :{self._port} ({self._transport})  total={total_w:.0f} W  (1 s push)")

    def _ingest(self, raw: bytes) -> None:
        try:
            payload = json.loads(raw.decode())
            total_w = float(payload.get("total", -1))
        except Exception:
            return
        if total_w < 0:
            return
        with self._lock:
            self._samples.append((time.monotonic(), total_w * 1000.0))  # W → mW

    def _reader_udp(self) -> None:
        while not self._stop.is_set():
            try:
                data, _ = self._sock.recvfrom(256)
            except (TimeoutError, OSError):
                continue
            self._ingest(data)

    def _reader_tcp(self) -> None:
        # Accept (re)connections from the daemon and read newline-delimited JSON.
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except (TimeoutError, OSError):
                continue
            conn.settimeout(1.0)
            buf = b""
            with conn:
                while not self._stop.is_set():
                    try:
                        chunk = conn.recv(4096)
                    except (TimeoutError, OSError):
                        continue
                    if not chunk:
                        break  # peer closed — go back to accept()
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if line.strip():
                            self._ingest(line)

    def _reader_http(self) -> None:
        # Tail the newline-delimited file the ingest sidecar appends HTTPS POSTs to.
        pos = 0
        while not self._stop.is_set():
            try:
                if os.path.exists(self._ingest_file):
                    with open(self._ingest_file, "rb") as f:
                        f.seek(pos)
                        for line in f:
                            if line.strip():
                                self._ingest(line)
                        pos = f.tell()
            except OSError:
                pass
            time.sleep(0.5)

    def stop(self) -> None:
        self._stop.set()
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass

    def snapshot_energy_mj(self) -> Optional[float]:
        return None

    def energy_from_counter(self, start_mj: float, end_mj: float) -> float:
        return (end_mj - start_mj) / 1000.0

    def energy_from_samples(self, t_start: float, t_end: float) -> Optional[float]:
        with self._lock:
            window = [(t, p) for t, p in self._samples if t_start <= t <= t_end]
        if len(window) < 2:
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


class CompositeTracker:
    """Runs several energy trackers at once so a single benchmark run records
    energy from every source simultaneously.

    Children are keyed by source name. Conventional keys:
      ``gpu``  — GPU-card energy (NVIDIA driver: SshGpuTracker / GPUTracker)
      ``wall`` — total wall-plug energy (ShellyTracker)

    Per-request energy is read from each child independently in ``_dispatch``;
    this wrapper just owns the children's lifecycle and reporting.
    """

    def __init__(self, children: "dict[str, object]") -> None:
        self.children = children

    @property
    def available(self) -> bool:
        return any(getattr(t, "available", False) for t in self.children.values())

    @property
    def method(self) -> str:
        # e.g. "gpu:polling+wall:shelly-udp"
        return "+".join(f"{n}:{getattr(t, 'method', 'none')}" for n, t in self.children.items()) or "none"

    def start(self) -> None:
        for t in self.children.values():
            t.start()

    def stop(self) -> None:
        for t in self.children.values():
            try:
                t.stop()
            except Exception:
                pass

    def power_samples(self) -> list:
        # The single power-timeline chart plots the GPU trace if present,
        # otherwise the first available source.
        for name in ("gpu", "wall"):
            t = self.children.get(name)
            if t is not None and getattr(t, "available", False):
                return t.power_samples()
        for t in self.children.values():
            if getattr(t, "available", False):
                return t.power_samples()
        return []


def _energy_for(
    tracker,
    e_start: Optional[float],
    e_end: Optional[float],
    t_start: float,
    t_end: float,
) -> Optional[float]:
    """Integrate one tracker's energy over a request window (None if unavailable)."""
    if tracker is None or not getattr(tracker, "available", False):
        return None
    if e_start is not None and e_end is not None and getattr(tracker, "_use_counter", False):
        return tracker.energy_from_counter(e_start, e_end)
    return tracker.energy_from_samples(t_start, t_end)


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


def _read_workload_seed(path: Path) -> Optional[int]:
    """Read the prepare-time seed from a workload CSV's ``seed`` column (first row).

    Returns None for workloads written before the column existed."""
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            reader.fieldnames = [h.strip().lower() for h in (reader.fieldnames or [])]
            for row in reader:
                raw = (row.get("seed") or "").strip()
                return int(raw) if raw else None
    except (OSError, ValueError):
        return None
    return None


def _load_prompts(path: Path, model: str, max_tokens: Optional[int], interval_ms: float) -> list[WorkloadEntry]:
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    entries = []
    for i, line in enumerate(lines):
        body: dict = {"model": model, "messages": [{"role": "user", "content": line}]}
        # Omit max_tokens entirely when unset/<=0 so responses are never truncated.
        if max_tokens is not None and max_tokens > 0:
            body["max_tokens"] = max_tokens
        entries.append(
            WorkloadEntry(
                request_id=f"req-{i + 1:04d}",
                arrival_offset_ms=i * interval_ms,
                body=body,
            )
        )
    return entries


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
    # Energy is measured per source, simultaneously when both are enabled:
    #   energy_gpu_j  — GPU-card energy from the NVIDIA driver (nvidia-smi / NVML)
    #   energy_wall_j — total wall-plug energy from the Shelly smart plug(s)
    energy_gpu_j: Optional[float]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    error: Optional[str]
    t_start: float
    t_end: float
    sent_at: str
    received_at: str
    energy_wall_j: Optional[float] = None
    scenario: str = ""
    # Scheduler view at decision time, from Logos response headers
    # (X-Logos-Warmth-State / X-Logos-ETTFT-Ms); None for direct Ollama.
    # warmth_state: -1 = cold, 0 = warm but not running, 1+x = running with
    # x requests queued.
    warmth_state: Optional[int] = None
    ettft_ms: Optional[float] = None
    # Full generated text and the backend's finish_reason ("stop", "length", …).
    # Logged so truncated/empty/garbage responses are visible after the run —
    # e.g. finish_reason="length" means the answer was cut off by a token cap.
    response_text: str = ""
    finish_reason: Optional[str] = None

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
    def energy_j(self) -> Optional[float]:
        """Primary energy for charts/back-compat: GPU if measured, else wall."""
        return self.energy_gpu_j if self.energy_gpu_j is not None else self.energy_wall_j

    def _energy_per_token_mj(self, energy: Optional[float]) -> Optional[float]:
        if energy is not None and self.completion_tokens:
            return energy / self.completion_tokens * 1000.0
        return None

    @property
    def energy_per_token_mj(self) -> Optional[float]:
        return self._energy_per_token_mj(self.energy_j)

    @property
    def energy_per_token_gpu_mj(self) -> Optional[float]:
        return self._energy_per_token_mj(self.energy_gpu_j)

    @property
    def energy_per_token_wall_mj(self) -> Optional[float]:
        return self._energy_per_token_mj(self.energy_wall_j)


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


# httpx connection-pool limits for the load runners. The benchmark dispatches
# OPEN-LOOP (a new request every 1/rate s regardless of how many are in flight),
# so when the server serves slower than the offered rate, in-flight requests
# accumulate. Steady-state in-flight ≈ offered_rate × REQUEST_TIMEOUT_S — at most
# a few thousand for the benchmark patterns. httpx's DEFAULT max_connections=100
# capped concurrency far below that: every excess dispatch blocked acquiring a
# pool slot and, after REQUEST_TIMEOUT_S elapsed, failed with PoolTimeout WITHOUT
# EVER REACHING THE SERVER. Those never-sent requests inflated the error rate with
# a pure client-side artifact and recorded a bogus sent_at/ttlt (≈ the full
# timeout). Uncapping the pool lets every offered request actually reach the
# orchestrator, so the benchmark measures the server and sent_at is the real
# on-wire send time. _raise_fd_limit() (called from main) ensures the process has
# enough file descriptors for the resulting socket count.
_HTTP_LIMITS = httpx.Limits(max_connections=None, max_keepalive_connections=50)

# Hard drain cap: after the LAST request of a pattern is fired, wait at most this
# many seconds for the still-in-flight requests to finish, then abandon the
# stragglers (recorded as errors) so the run can never hang on a stuck request —
# e.g. a wedged lane while LOGOS_TIMEOUT_S disables the per-request client
# timeout. Override with LOGOS_BENCH_DRAIN_CAP_S; <=0 disables the cap.
try:
    _DRAIN_CAP_S = float(os.getenv("LOGOS_BENCH_DRAIN_CAP_S", "3600") or 3600)
except (TypeError, ValueError):
    _DRAIN_CAP_S = 3600.0


def _build_load_client(timeout_s: float) -> httpx.AsyncClient:
    """AsyncClient for the load runners: uncapped connection pool and an explicit
    timeout with ``pool=None`` so a dispatch never blocks waiting for a pool slot.
    Read/write/connect still honour ``timeout_s``. With no pool wait, the sent_at
    captured just before ``client.stream`` is the true moment the request goes out."""
    timeout = httpx.Timeout(timeout_s, pool=None)
    # verify=True: the load client carries the logos_key in headers and targets the
    # public Logos URL (valid Let's Encrypt cert via Traefik), so keep MITM
    # protection on. (The ollama path uses plain http, where verify is moot.)
    return httpx.AsyncClient(timeout=timeout, limits=_HTTP_LIMITS, verify=True)


def _raise_fd_limit() -> None:
    """Raise the soft open-file limit toward the hard limit so the uncapped httpx
    pool can hold the thousands of concurrent streaming sockets that open-loop
    dispatch into an overloaded server produces. The common 1024 default soft
    limit is far below offered_rate × REQUEST_TIMEOUT_S and would reintroduce the
    very connection starvation we just removed (as ConnectError/OSError)."""
    try:
        import resource
    except ImportError:  # non-Unix platform — nothing to do
        return
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    target = hard if hard != resource.RLIM_INFINITY else 1_048_576
    if soft >= target:
        return
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
        print(f"  [fd] raised RLIMIT_NOFILE soft {soft} -> {target}", flush=True)
    except (ValueError, OSError) as exc:
        print(f"  [fd] could not raise RLIMIT_NOFILE (soft={soft}): {exc}", flush=True)


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
    # Request a final usage chunk so prompt/completion token counts are reported
    # in streaming mode. Logos injects usage on its own, but raw Ollama (and
    # vanilla OpenAI-compatible servers) only emit it when explicitly asked —
    # without this, every Ollama row was missing token counts (and the derived
    # tpot / throughput / energy-per-token metrics).
    payload = {**entry.body, "stream": True, "stream_options": {"include_usage": True}}
    # No completion-token limit: a falsy/absent max_tokens means "let the backend
    # decide when to stop". Strip it defensively so a stale workload CSV that still
    # carries max_tokens=512 can't silently truncate answers (issue: completion
    # tokens pinned to exactly the cap). See benchmark_config.GSM8K_MAX_TOKENS.
    if not payload.get("max_tokens"):
        payload.pop("max_tokens", None)

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
    response_text = ""
    finish_reason: Optional[str] = None

    # One energy snapshot per source (gpu / wall). A plain (non-composite)
    # tracker — e.g. the warmup _NullTracker — is treated as a single "gpu" source.
    energy_sources: "dict[str, object]" = getattr(tracker, "children", None) or {"gpu": tracker}
    e_start = {name: t.snapshot_energy_mj() for name, t in energy_sources.items()}
    # Captured immediately before client.stream(). With the load client's pool
    # uncapped (see _build_load_client), the stream call does not block waiting for
    # a connection slot, so this timestamp is the true moment the request is sent —
    # not, as before, the moment a request entered a saturated pool queue.
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
                    energy_gpu_j=None,
                    energy_wall_j=None,
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
            content_parts: list[str] = []

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

                for choice in chunk.get("choices", []):
                    delta = choice.get("delta", {})
                    piece = delta.get("content") or delta.get("reasoning") or delta.get("reasoning_content")
                    if piece:
                        content_parts.append(piece)
                        if not first_token:
                            # Trigger TTFT on the first generated token, whether it
                            # is normal "content" or a reasoning token (Qwen3/vLLM).
                            ttft_ms = (time.monotonic() - t_start) * 1000.0
                            first_token = True
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]

                if usage := chunk.get("usage"):
                    prompt_tokens = usage.get("prompt_tokens")
                    completion_tokens = usage.get("completion_tokens")

            response_text = "".join(content_parts)

    except Exception as exc:
        # httpx timeout exceptions stringify to "" — without the class name
        # the results CSV shows status_code=0 with an empty error column and
        # timeouts are indistinguishable from other transport failures.
        detail = str(exc).strip()
        error = (f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__)[:500]

    t_end = time.monotonic()
    e_end = {name: t.snapshot_energy_mj() for name, t in energy_sources.items()}
    received_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    ttlt_ms = (t_end - t_start) * 1000.0

    energy_gpu_j = _energy_for(energy_sources.get("gpu"), e_start.get("gpu"), e_end.get("gpu"), t_start, t_end)
    energy_wall_j = _energy_for(energy_sources.get("wall"), e_start.get("wall"), e_end.get("wall"), t_start, t_end)

    return RequestResult(
        request_id=entry.request_id,
        model=model,
        mode=entry.mode,
        priority=entry.priority,
        status_code=status_code,
        ttft_ms=ttft_ms,
        ttlt_ms=ttlt_ms,
        energy_gpu_j=energy_gpu_j,
        energy_wall_j=energy_wall_j,
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
        response_text=response_text,
        finish_reason=finish_reason,
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


class _LiveStats:
    """Aggregates request stats for a once-per-second progress line.

    Counts requests SENT (dispatched), SUCCESS responses, and ERROR responses
    (anything not 2xx/3xx, including ERR=200 stream drops), plus live throughput
    and average/p50 TTFT. ``mark_sent`` is called when a request is launched and
    ``mark_done`` when its result returns; ``report_loop`` prints every second.
    """

    def __init__(self, total: int, label: str = "") -> None:
        self.total = total
        self.label = label
        self.sent = 0
        self.success = 0
        self.error = 0
        self._ttfts: list[float] = []
        self._t0 = time.monotonic()
        # Longest line emitted so far — used to pad/overwrite when rewriting the
        # single live status line in place (see _emit).
        self._max_len = 0

    def mark_sent(self) -> None:
        self.sent += 1

    def mark_done(self, r: "RequestResult") -> None:
        if r.success:
            self.success += 1
        else:
            self.error += 1
        if r.ttft_ms is not None:
            self._ttfts.append(r.ttft_ms)

    @property
    def in_flight(self) -> int:
        return self.sent - self.success - self.error

    def _line(self) -> str:
        elapsed = max(1e-9, time.monotonic() - self._t0)
        done = self.success + self.error
        if self._ttfts:
            avg = sum(self._ttfts) / len(self._ttfts)
            s = sorted(self._ttfts)
            p50 = s[len(s) // 2]
            ttft = f"avg_ttft={avg:.0f}ms p50_ttft={p50:.0f}ms"
        else:
            ttft = "avg_ttft=—"
        return (
            f"  [live]{self.label} t={elapsed:.0f}s "
            f"sent={self.sent}/{self.total} ok={self.success} err={self.error} "
            f"inflight={self.in_flight} | {done/elapsed:.2f} done/s {ttft}"
        )

    def _emit(self, line: str, *, final: bool) -> None:
        """Rewrite the single live status line in place with a carriage return.

        Per-second updates overwrite one line instead of appending thousands of
        rows, so ``tail``-ing the log shows the current state, not scrollback.
        A trailing newline is written only on the final snapshot so the live
        line is "committed" and later output starts cleanly below it.
        """
        self._max_len = max(self._max_len, len(line))
        padded = line.ljust(self._max_len)
        end = "\n" if final else ""
        sys.stdout.write("\r" + padded + end)
        sys.stdout.flush()

    async def report_loop(self, interval: float = 1.0) -> None:
        try:
            while True:
                await asyncio.sleep(interval)
                self._emit(self._line(), final=False)
        except asyncio.CancelledError:
            self._emit(self._line(), final=True)  # final snapshot, commit the line
            raise


def _abandoned_result(entry: WorkloadEntry, scenario: str, waited_s: float) -> RequestResult:
    """Synthetic error result for a request still in-flight when the drain cap
    expired. Recorded as an error (status_code=0) so the run's error rate
    reflects the stuck requests instead of silently dropping them."""
    now = time.monotonic()
    iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return RequestResult(
        request_id=entry.request_id,
        model=entry.body.get("model", "?"),
        mode=entry.mode,
        priority=entry.priority,
        status_code=0,
        ttft_ms=None,
        ttlt_ms=None,
        energy_gpu_j=None,
        energy_wall_j=None,
        prompt_tokens=None,
        completion_tokens=None,
        error=f"drain-cap: still in-flight after {waited_s:.0f}s drain wait — abandoned",
        t_start=now,
        t_end=now,
        sent_at=iso,
        received_at=iso,
        scenario=scenario,
    )


async def _drain_gather(
    tasks: list[asyncio.Task],
    entries: list[WorkloadEntry],
    results: list[RequestResult],
    stats: "_LiveStats",
    lock: asyncio.Lock,
    scenario: str,
    label_prefix: str,
) -> None:
    """Await all dispatched request tasks, but at most ``_DRAIN_CAP_S`` seconds
    after the last was fired. Any still pending past the cap are cancelled and
    recorded as drain-cap errors, so a stuck request can never hang the run.
    ``tasks`` and ``entries`` must be index-aligned (one task per entry, in
    dispatch order)."""
    if not tasks:
        return
    if not _DRAIN_CAP_S or _DRAIN_CAP_S <= 0:
        await asyncio.gather(*tasks, return_exceptions=True)
        return
    _, pending = await asyncio.wait(tasks, timeout=_DRAIN_CAP_S)
    if not pending:
        return
    pending_set = set(pending)
    abandoned = [entry for task, entry in zip(tasks, entries) if task in pending_set]
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    async with lock:
        for entry in abandoned:
            r = _abandoned_result(entry, scenario, _DRAIN_CAP_S)
            results.append(r)
            stats.mark_done(r)
    print(
        f"  {label_prefix}[drain] cap {_DRAIN_CAP_S:.0f}s reached after all requests fired — "
        f"abandoned {len(abandoned)} stuck request(s) (recorded as errors).",
        flush=True,
    )


async def run_sequential(
    workload: list[WorkloadEntry],
    base_url: str,
    logos_key: Optional[str],
    tracker,
    timeout_s: float,
    scenario: str,
    model_map: dict[str, str],
    dispatch_rate: float = 1.0,
    label_prefix: str = "",
    stats: "Optional[_LiveStats]" = None,
    live: bool = True,
) -> list[RequestResult]:
    """Open-loop constant-rate dispatch: fire one request every 1/dispatch_rate
    seconds WITHOUT waiting for the previous response. Dispatch wall-time is
    n/dispatch_rate, independent of how fast the server responds (a request that
    is slow or times out does not hold up the next send). Deterministic spacing
    distinguishes it from the poisson pattern's random spacing.

    When ``stats`` is supplied the caller owns the live counters (used by
    run_mixed to aggregate three concurrent sub-streams into ONE live line);
    ``live=False`` then suppresses this runner's own per-second reporter so the
    three sub-streams don't fight over the single ``\\r`` status line.
    """
    results: list[RequestResult] = []
    n = len(workload)
    width = len(str(n))
    done = [0]
    lock = asyncio.Lock()
    if stats is None:
        stats = _LiveStats(n, label=(f" {label_prefix.strip()}" if label_prefix.strip() else ""))
    interval = (1.0 / dispatch_rate) if dispatch_rate and dispatch_rate > 0 else 0.0

    async with _build_load_client(timeout_s) as client:
        reporter = asyncio.create_task(stats.report_loop(1.0)) if live else None

        async def _one(entry: WorkloadEntry) -> None:
            r = await _dispatch(
                client,
                base_url,
                logos_key,
                entry,
                0.0,
                tracker,
                sequential=True,  # send immediately when this task runs (runner controls the rate)
                scenario=scenario,
                model_map=model_map,
            )
            async with lock:
                results.append(r)
                done[0] += 1
                stats.mark_done(r)
                # Successes are summarized by the single-line live stats (no
                # per-request newline spam); only surface failures inline.
                if not r.success:
                    print(f"\n  {label_prefix}[{done[0]:{width}}/{n}] {r.request_id}  {_result_line(r)}", flush=True)

        tasks: list[asyncio.Task] = []
        for i, entry in enumerate(workload):
            stats.mark_sent()
            tasks.append(asyncio.create_task(_one(entry)))
            if i < n - 1 and interval > 0:
                await asyncio.sleep(interval)

        await _drain_gather(tasks, workload, results, stats, lock, scenario, label_prefix)
        if reporter is not None:
            reporter.cancel()
            try:
                await reporter
            except asyncio.CancelledError:
                pass
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

    async with _build_load_client(timeout_s) as client:

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
                if not r.success:
                    print(f"\n  [{completed:{width}}/{n}] {r.request_id}  {_result_line(r)}", flush=True)

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
    stats: "Optional[_LiveStats]" = None,
    live: bool = True,
) -> list[RequestResult]:
    """Open-loop bursts: fire burst_size fully-concurrent requests, wait
    inter_burst_delay_s, then fire the next burst — WITHOUT waiting for the
    previous burst's responses. Dispatch wall-time is (n/burst_size)·delay,
    independent of how fast the server responds.

    ``stats``/``live`` as in run_sequential: run_mixed passes a shared stats and
    live=False so the three sub-streams share ONE aggregate live line.
    """
    results: list[RequestResult] = []
    n = len(workload)
    width = len(str(n))
    done_counter = [0]
    lock = asyncio.Lock()
    if stats is None:
        stats = _LiveStats(n, label=(f" {label_prefix.strip()}" if label_prefix.strip() else ""))

    async with _build_load_client(timeout_s) as client:
        reporter = asyncio.create_task(stats.report_loop(1.0)) if live else None

        async def _one(entry: WorkloadEntry) -> None:
            r = await _dispatch(
                client,
                base_url,
                logos_key,
                entry,
                0.0,
                tracker,
                sequential=True,  # send immediately; the burst schedule controls dispatch timing
                scenario=scenario,
                model_map=model_map,
            )
            async with lock:
                results.append(r)
                done_counter[0] += 1
                stats.mark_done(r)
                if not r.success:
                    print(
                        f"\n  {label_prefix}[{done_counter[0]:{width}}/{n}] {r.request_id}  {_result_line(r)}",
                        flush=True,
                    )

        tasks: list[asyncio.Task] = []
        for batch_idx, batch_start in enumerate(range(0, n, burst_size)):
            if batch_idx > 0 and inter_burst_delay_s > 0:
                await asyncio.sleep(inter_burst_delay_s)
            for entry in workload[batch_start : batch_start + burst_size]:
                stats.mark_sent()
                tasks.append(asyncio.create_task(_one(entry)))

        await _drain_gather(tasks, workload, results, stats, lock, scenario, label_prefix)
        if reporter is not None:
            reporter.cancel()
            try:
                await reporter
            except asyncio.CancelledError:
                pass

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
    stats: "Optional[_LiveStats]" = None,
    live: bool = True,
) -> list[RequestResult]:
    """Dispatch requests with Poisson-distributed inter-arrival times.

    lam events are expected per zeitraum_s seconds, giving a mean inter-arrival time of
    zeitraum_s / lam seconds.  Requests are launched independently and can overlap.

    ``stats``/``live`` as in run_sequential: run_mixed passes a shared stats and
    live=False so the three sub-streams share ONE aggregate live line.
    """
    results: list[RequestResult] = []
    n = len(workload)
    width = len(str(n))
    done_counter = [0]
    lock = asyncio.Lock()
    rate = lam / zeitraum_s  # effective rate in req/s
    if stats is None:
        stats = _LiveStats(n, label=(f" {label_prefix.strip()}" if label_prefix.strip() else ""))

    async with _build_load_client(timeout_s) as client:
        start_mono = time.monotonic()
        reporter = asyncio.create_task(stats.report_loop(1.0)) if live else None

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
                stats.mark_done(r)
                if not r.success:
                    print(
                        f"\n  {label_prefix}[{done_counter[0]:{width}}/{n}] {r.request_id}  {_result_line(r)}",
                        flush=True,
                    )

        tasks: list[asyncio.Task] = []
        for i, entry in enumerate(workload):
            stats.mark_sent()
            tasks.append(asyncio.create_task(_one(entry)))
            if i < n - 1:
                await asyncio.sleep(random.expovariate(rate))

        await _drain_gather(tasks, workload, results, stats, lock, scenario, label_prefix)
        if reporter is not None:
            reporter.cancel()
            try:
                await reporter
            except asyncio.CancelledError:
                pass

    return results


async def _aggregate_report_loop(agg: "_LiveStats", parts: "list[_LiveStats]", interval: float = 1.0) -> None:
    """Single live reporter for run_mixed: fold the three concurrent sub-stream
    counters into one _LiveStats and emit ONE in-place status line, so the three
    sub-streams never fight over the single `\\r` line (the newline-spam bug)."""

    def _fold() -> None:
        agg.sent = sum(p.sent for p in parts)
        agg.success = sum(p.success for p in parts)
        agg.error = sum(p.error for p in parts)
        agg._ttfts = [t for p in parts for t in p._ttfts]

    try:
        while True:
            await asyncio.sleep(interval)
            _fold()
            agg._emit(agg._line(), final=False)
    except asyncio.CancelledError:
        _fold()
        agg._emit(agg._line(), final=True)
        raise


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

    # The three sub-streams run concurrently. If each kept its own per-second
    # reporter they'd all rewrite the single `\r` status line at once, producing
    # garbled, newline-split output. Instead give each sub-stream a shared
    # _LiveStats (live=False → no own reporter) and run ONE aggregate reporter
    # over the whole 1000-request mixed pattern.
    stats_burst = _LiveStats(len(part_burst), label=" [B]")
    stats_poisson = _LiveStats(len(part_poisson), label=" [P]")
    stats_seq = _LiveStats(len(part_seq), label=" [S]")
    agg = _LiveStats(n, label=" mixed")
    agg_reporter = asyncio.create_task(_aggregate_report_loop(agg, [stats_burst, stats_poisson, stats_seq], 1.0))

    try:
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
                stats=stats_burst,
                live=False,
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
                stats=stats_poisson,
                live=False,
            ),
            run_sequential(
                part_seq,
                base_url,
                logos_key,
                tracker,
                timeout_s,
                scenario,
                model_map,
                dispatch_rate=(lam / zeitraum_s if zeitraum_s else 1.0),
                label_prefix="[S]",
                stats=stats_seq,
                live=False,
            ),
        )
    finally:
        agg_reporter.cancel()
        try:
            await agg_reporter
        except asyncio.CancelledError:
            pass
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

    async with _build_load_client(timeout_s + 5.0) as client:
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
        # Report each model the instant its warmup request finishes, with a
        # periodic heartbeat for the ones still cold-loading — so the log shows
        # live progress instead of going silent for minutes during warmup.
        task_to_model = {t: m for t, m in zip(tasks, models)}
        pending = set(tasks)
        total = len(models)
        t0 = time.monotonic()
        deadline = t0 + timeout_s
        heartbeat_s = 15.0
        all_ok = True

        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            done, pending = await asyncio.wait(
                pending, timeout=min(heartbeat_s, remaining), return_when=asyncio.FIRST_COMPLETED
            )
            elapsed = time.monotonic() - t0
            if not done:
                still = ", ".join(sorted(task_to_model[t] for t in pending))
                print(
                    f"  [warmup] … {total - len(pending)}/{total} ready after {elapsed:.0f}s; "
                    f"still loading: {still}",
                    flush=True,
                )
                continue
            for task in done:
                model = task_to_model[task]
                tag = f"[{total - len(pending)}/{total}, +{elapsed:.0f}s]"
                try:
                    r = task.result()
                    if r.success:
                        ttft = f"TTFT={r.ttft_ms:.0f}ms" if r.ttft_ms else "no TTFT"
                        print(f"  [warmup] {model:<{width}}  OK      {ttft}  {tag}", flush=True)
                    else:
                        all_ok = False
                        msg = (r.error or "").replace("\n", " ").strip()
                        print(f"  [warmup] {model:<{width}}  FAIL    HTTP {r.status_code}  {tag}", flush=True)
                        if msg:
                            print(f"  [warmup] {' ' * width}    └─ {msg[:500]}", flush=True)
                except Exception as exc:
                    all_ok = False
                    print(f"  [warmup] {model:<{width}}  ERROR   {exc}  {tag}", flush=True)

        for task in pending:  # whatever is left once the deadline passes
            task.cancel()
            all_ok = False
            print(f"  [warmup] {task_to_model[task]:<{width}}  TIMEOUT (>{timeout_s:.0f}s)", flush=True)

    print("  [warmup] Done.", flush=True)
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
    e_gpu = [r.energy_gpu_j for r in ok if r.energy_gpu_j is not None]
    e_wall = [r.energy_wall_j for r in ok if r.energy_wall_j is not None]
    ept_gpu = [r.energy_per_token_gpu_mj for r in ok if r.energy_per_token_gpu_mj is not None]
    ept_wall = [r.energy_per_token_wall_mj for r in ok if r.energy_per_token_wall_mj is not None]
    tput = [r.throughput_tok_s for r in ok if r.throughput_tok_s is not None]

    return {
        "scenario": scenario,
        # e.g. "gpu:polling+wall:shelly-udp" — names every energy source measured
        "energy_method": energy_method,
        "total_requests": len(results),
        "successful_requests": len(ok),
        "failed_requests": fail,
        "error_rate_pct": fail / len(results) * 100 if results else math.nan,
        **_stats(ttft, "ttft_ms"),
        **_stats(ttlt, "ttlt_ms"),
        **_stats(tpot, "tpot_ms"),
        # GPU = NVIDIA driver (nvidia-smi); wall = Shelly smart plug.
        **_stats(e_gpu, "energy_gpu_j"),
        **_stats(e_wall, "energy_wall_j"),
        **_stats(ept_gpu, "energy_per_token_gpu_mj"),
        **_stats(ept_wall, "energy_per_token_wall_mj"),
        "throughput_tok_s_mean": sum(tput) / len(tput) if tput else math.nan,
        "total_prompt_tokens": sum(r.prompt_tokens or 0 for r in ok),
        "total_completion_tokens": sum(r.completion_tokens or 0 for r in ok),
        # NOTE: these sum per-request time-window energy, which over-counts under
        # concurrency (overlapping windows). The authoritative scenario totals are
        # total_energy_{gpu,wall}_j, added by _overall_energy_metrics (integrated
        # power over the whole run); energy_per_request/token come from those.
        "total_energy_gpu_j_request_windows": sum(e_gpu) if e_gpu else math.nan,
        "total_energy_wall_j_request_windows": sum(e_wall) if e_wall else math.nan,
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
    "energy_gpu_j",  # GPU-card energy from the NVIDIA driver (nvidia-smi / NVML)
    "energy_wall_j",  # total wall-plug energy from the Shelly smart plug
    "energy_per_token_gpu_mj",
    "energy_per_token_wall_mj",
    "throughput_tok_s",
    "prompt_tokens",
    "completion_tokens",
    "finish_reason",
    "sent_at",
    "received_at",
    "error",
    "response_text",
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
                    "energy_gpu_j": _f(r.energy_gpu_j),
                    "energy_wall_j": _f(r.energy_wall_j),
                    "energy_per_token_gpu_mj": _f(r.energy_per_token_gpu_mj),
                    "energy_per_token_wall_mj": _f(r.energy_per_token_wall_mj),
                    "throughput_tok_s": _f(r.throughput_tok_s),
                    "prompt_tokens": _f(r.prompt_tokens),
                    "completion_tokens": _f(r.completion_tokens),
                    "finish_reason": r.finish_reason or "",
                    "sent_at": r.sent_at,
                    "received_at": r.received_at,
                    "error": r.error or "",
                    # Full text kept so truncation/garbage is auditable; newlines
                    # collapsed to keep each request on one CSV row.
                    "response_text": " ".join((r.response_text or "").split()),
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


def _write_energy_timeline_csv(out_path: Path, tracker, t0: float, wall_s: float) -> None:
    """Per-second power/energy time-series, one row per (second, source).

    Energy is a system-level, scenario-wide quantity: under concurrency many
    requests share the GPU at once, so per-request time-window attribution
    double-counts wildly (it produced totals in the billions of joules). This
    raw per-second trace is the honest record — integrate it over the run for
    the scenario total, then divide by request/token counts (see summary).

    Columns: t_offset_s, source, power_w, energy_j_interval, energy_j_cumulative
    where source is "gpu" (NVIDIA driver) or "wall" (Shelly plug).
    """
    sources = getattr(tracker, "children", None) or {"gpu": tracker}
    rows: list[dict] = []
    for name, child in sources.items():
        try:
            samples = child.power_samples()  # [(t_mono, power_mW), ...]
        except Exception:
            samples = []
        if not samples:
            continue
        # Mean power per 1-second bucket; cumulative energy via rectangle sum.
        buckets: dict[int, list[float]] = {}
        for t, p_mw in samples:
            buckets.setdefault(int(t - t0), []).append(p_mw / 1000.0)  # W
        cumulative = 0.0
        for sec in range(0, int(math.ceil(wall_s)) + 1):
            ws = buckets.get(sec)
            if not ws:
                continue
            power_w = sum(ws) / len(ws)
            cumulative += power_w  # 1-second bucket → W·s = J
            rows.append(
                {
                    "t_offset_s": sec,
                    "source": name,
                    "power_w": f"{power_w:.3f}",
                    "energy_j_interval": f"{power_w:.3f}",
                    "energy_j_cumulative": f"{cumulative:.3f}",
                }
            )
    rows.sort(key=lambda r: (r["t_offset_s"], r["source"]))
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["t_offset_s", "source", "power_w", "energy_j_interval", "energy_j_cumulative"],
        )
        w.writeheader()
        w.writerows(rows)


def _overall_energy_metrics(tracker, t_start: float, t_end: float, n_ok: int, n_tokens: int) -> dict:
    """Scenario-wide energy by integrating the power trace over the whole run,
    then attributing per-request / per-token by simple division (not per-request
    time windows, which over-count under concurrency).

    Emits, per source: total_energy_<src>_j, energy_per_request_<src>_j,
    energy_per_token_<src>_mj.
    """
    sources = getattr(tracker, "children", None) or {"gpu": tracker}
    out: dict = {}
    for name in ("gpu", "wall"):
        child = sources.get(name)
        if child is None or not getattr(child, "available", False):
            continue
        total_j = child.energy_from_samples(t_start, t_end)
        if total_j is None:
            continue
        out[f"total_energy_{name}_j"] = total_j
        out[f"energy_per_request_{name}_j"] = (total_j / n_ok) if n_ok else math.nan
        out[f"energy_per_token_{name}_mj"] = (total_j * 1000.0 / n_tokens) if n_tokens else math.nan
    return out


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


def _warmth_bucket(ws: Optional[int]) -> Optional[str]:
    """Map the raw warmth_state integer to a human bucket.

    -1 → cold (model not resident), 0 → warm-idle (loaded/sleeping, no request
    running), >=1 → hot (serving, possibly queued). Charting the raw integer
    (which ranges -1..hundreds) was meaningless — these three buckets are the
    comparison that matters for sleep-vs-nosleep TTFT.
    """
    if ws is None:
        return None
    if ws < 0:
        return "cold"
    if ws == 0:
        return "warm-idle"
    return "hot"


def _warmth_ttft_chart(results: list[RequestResult], path: Path) -> None:
    """TTFT distribution bucketed by warmth (cold / warm-idle / hot)."""
    if not _PLOT:
        return
    order = ["cold", "warm-idle", "hot"]
    buckets: dict[str, list[float]] = {b: [] for b in order}
    for r in results:
        if not r.success or r.ttft_ms is None:
            continue
        b = _warmth_bucket(r.warmth_state)
        if b is not None:
            buckets[b].append(r.ttft_ms)
    present = [(b, buckets[b]) for b in order if buckets[b]]
    if not present:
        return
    labels = [f"{b}\n(n={len(v)}, p50={_pct(v, 50):.0f}ms)" for b, v in present]
    data = [v for _, v in present]
    fig, ax = plt.subplots(figsize=(max(6, len(present) * 2.5), 5))
    ax.boxplot(data, tick_labels=labels, patch_artist=True, showfliers=False)
    ax.set_ylabel("TTFT (ms)")
    ax.set_title("TTFT by warmth state")
    ax.grid(True, alpha=0.25, axis="y")
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
    # Per-request-window energy charts. NOTE: these attribute energy by each
    # request's own time window, which over-counts under concurrency — read them
    # together with the authoritative scenario-level energy in results_summary.csv
    # (integrated power ÷ counts) and the per-second trace in energy_timeline.csv.
    energy = [r.energy_j for r in ok if r.energy_j is not None]
    if energy:
        _dist_chart(
            energy,
            "Energy per Request (per-request window)",
            "Energy (J)",
            out_dir / "chart_energy_per_request.png",
        )
        _dist_chart(
            [r.energy_per_token_mj for r in ok if r.energy_per_token_mj is not None],
            "Energy per Output Token (per-request window)",
            "Energy (mJ/token)",
            out_dir / "chart_energy_per_token.png",
        )
    _power_timeline(tracker.power_samples(), results, t0, out_dir / "chart_power_timeline.png")
    _scatter_energy_ttlt(results, out_dir / "chart_energy_vs_ttlt.png")
    _per_model_chart(results, "ttft_ms", "TTFT (ms)", out_dir / "chart_ttft_by_model.png")
    _per_model_chart(results, "energy_j", "Energy (J)", out_dir / "chart_energy_by_model.png")
    _warmth_ttft_chart(results, out_dir / "chart_ttft_by_warmth.png")
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


# ── Shelly HTTP ingest sidecar (Traefik-routed wall power) ─────────────────
#
# When only HTTPS/443 passes the firewall to the benchmark host, the Pi daemon
# POSTs readings to https://<host>/shelly-ingest. Traefik (already running as a
# persistent service in /opt/logos) forwards that to this short-lived sidecar
# container — discovered purely via Docker-provider labels, so NO Traefik
# restart or compose edit is needed. The sidecar appends each reading to a
# bind-mounted NDJSON file that the http-mode ShellyTracker tails. The pipeline
# starts it at run start and removes it at teardown.

_SHELLY_INGEST_NAME = "bench-shelly-ingest"
_SHELLY_INGEST_DIR = "/tmp/bench-shelly-ingest"
_SHELLY_INGEST_FILE = f"{_SHELLY_INGEST_DIR}/readings.ndjson"
_SHELLY_INGEST_PATHPREFIX = "/shelly-ingest"

# Minimal HTTP server that runs INSIDE the sidecar: append each POSTed JSON body
# as one NDJSON line to the bind-mounted file; GET / is a health check.
_SHELLY_INGEST_SERVER = (
    "import http.server,json\n"
    "P='/data/readings.ndjson'\n"
    "class H(http.server.BaseHTTPRequestHandler):\n"
    " def do_POST(self):\n"
    "  try:\n"
    "   n=int(self.headers.get('Content-Length') or 0); b=self.rfile.read(n); json.loads(b)\n"
    "   f=open(P,'ab'); f.write(b.rstrip()+b'\\n'); f.close(); self.send_response(204)\n"
    "  except Exception: self.send_response(400)\n"
    "  self.end_headers()\n"
    " def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b'ok')\n"
    " def log_message(self,*a): pass\n"
    "http.server.HTTPServer(('0.0.0.0',8000),H).serve_forever()\n"
)


def _docker(use_sudo: bool, *args: str, capture: bool = False) -> subprocess.CompletedProcess:
    cmd = (["sudo"] if use_sudo else []) + ["docker", *args]
    return subprocess.run(cmd, capture_output=capture, text=True)


def _traefik_network(use_sudo: bool, container: str = "traefik") -> Optional[str]:
    """Return the first docker network the Traefik container is attached to."""
    r = _docker(
        use_sudo,
        "inspect",
        container,
        "--format",
        "{{range $k,$v := .NetworkSettings.Networks}}{{$k}}\n{{end}}",
        capture=True,
    )
    if r.returncode != 0:
        return None
    nets = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    return nets[0] if nets else None


def _start_shelly_ingest_sidecar(use_sudo: bool, image: str) -> Optional[str]:
    """Start the Traefik-labelled HTTP ingest sidecar.

    Returns the host ingest-file path on success, or None (non-fatal) when
    Traefik is not running or the container cannot be started — the benchmark
    then simply records GPU energy only.
    """
    net = _traefik_network(use_sudo)
    if not net:
        print(
            "  [shelly] Traefik container not found/running — cannot route HTTPS "
            "ingest; wall power disabled this run."
        )
        return None
    os.makedirs(_SHELLY_INGEST_DIR, exist_ok=True)
    open(_SHELLY_INGEST_FILE, "w").close()  # fresh file per run
    _docker(use_sudo, "rm", "-f", _SHELLY_INGEST_NAME, capture=True)  # clear any stale sidecar
    labels = [
        "traefik.enable=true",
        f"traefik.http.routers.benchshelly.rule=PathPrefix(`{_SHELLY_INGEST_PATHPREFIX}`)",
        "traefik.http.routers.benchshelly.entrypoints=websecure",
        "traefik.http.routers.benchshelly.tls=true",
        "traefik.http.routers.benchshelly.tls.certresolver=letsencrypt",
        "traefik.http.routers.benchshelly.priority=200",
        "traefik.http.services.benchshelly.loadbalancer.server.port=8000",
    ]
    run_args = [
        "run",
        "-d",
        "--name",
        _SHELLY_INGEST_NAME,
        "--network",
        net,
        "--restart",
        "no",
        "-v",
        f"{_SHELLY_INGEST_DIR}:/data",
    ]
    for lb in labels:
        run_args += ["--label", lb]
    run_args += [image, "python3", "-u", "-c", _SHELLY_INGEST_SERVER]
    r = _docker(use_sudo, *run_args, capture=True)
    if r.returncode != 0:
        print(f"  [shelly] failed to start ingest sidecar: {(r.stderr or '').strip()[:200]}")
        return None
    print(
        f"  [shelly] ingest sidecar up on Traefik net '{net}' "
        f"(443 {_SHELLY_INGEST_PATHPREFIX} → :8000 → {_SHELLY_INGEST_FILE})"
    )
    return _SHELLY_INGEST_FILE


def _stop_shelly_ingest_sidecar(use_sudo: bool) -> None:
    _docker(use_sudo, "rm", "-f", _SHELLY_INGEST_NAME, capture=True)
    print("  [shelly] ingest sidecar removed.")


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


def _start_logos_via_ssh(
    logos_dir: str,
    relay_host: str,
    relay_user: str,
    ssh_key: Optional[str],
    use_sudo: bool,
) -> None:
    """Start Logos orchestrator by SSH-ing directly to the relay/logos host."""
    sudo = "sudo " if use_sudo else ""
    cmd_str = f"cd {shlex.quote(logos_dir)} && {sudo}docker compose up -d --no-recreate"
    parts = ["ssh", "-o", "StrictHostKeyChecking=no"]
    if ssh_key:
        parts += ["-i", ssh_key]
    parts += [f"{relay_user}@{relay_host}", cmd_str]
    print(f"  [logos] $ ssh {relay_user}@{relay_host} '{cmd_str}'")
    result = subprocess.run(parts)
    if result.returncode != 0:
        raise RuntimeError(f"'docker compose up' on {relay_host} failed with exit code {result.returncode}.")


def _set_calibration_window_enabled(
    logos_dir,
    enabled: bool,
    use_sudo: bool,
    relay_host: Optional[str] = None,
    relay_user: Optional[str] = None,
    ssh_key: Optional[str] = None,
) -> None:
    """Enable/disable the orchestrator's nightly calibration maintenance window
    (LOGOS_CALIB_ENABLED) in ``<logos_dir>/.env`` and recreate ONLY the
    orchestrator container so it picks up the change. Traefik and the DB are left
    untouched, so the Let's Encrypt cert is preserved.

    A benchmark MUST disable this for the duration of a run: otherwise the
    maintenance window can start a calibration session mid-run (when a worker is
    momentarily idle) and corrupt the measurements / contend for the GPU.
    Requires the orchestrator compose to pass LOGOS_CALIB_ENABLED through to the
    container (see logos/docker-compose.yaml).
    """
    val = "true" if enabled else "false"
    sudo = "sudo " if use_sudo else ""
    env_path = shlex.quote(f"{logos_dir}/.env")
    dir_q = shlex.quote(str(logos_dir))
    remote = (
        f"{sudo}touch {env_path} && "
        f"if {sudo}grep -q '^LOGOS_CALIB_ENABLED=' {env_path}; then "
        f"{sudo}sed -i 's/^LOGOS_CALIB_ENABLED=.*/LOGOS_CALIB_ENABLED={val}/' {env_path}; "
        f"else printf 'LOGOS_CALIB_ENABLED={val}\\n' | {sudo}tee -a {env_path} >/dev/null; fi && "
        f"cd {dir_q} && {sudo}docker compose up -d --no-deps --force-recreate logos-orchestrator"
    )
    if relay_host:
        parts = ["ssh", "-o", "StrictHostKeyChecking=no"]
        if ssh_key:
            parts += ["-i", ssh_key]
        parts += [f"{relay_user}@{relay_host}", remote]
    else:
        parts = ["bash", "-c", remote]
    print(f"  [calib-window] LOGOS_CALIB_ENABLED={val} — recreating orchestrator to apply ...")
    result = subprocess.run(parts)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to set LOGOS_CALIB_ENABLED={val} (exit {result.returncode}).")


def _set_logos_sleep_mode_via_ssh(
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    workernode_dir: str,
    enabled: bool,
    use_sudo: bool = True,
    relay_host: Optional[str] = None,
    relay_user: Optional[str] = None,
) -> None:
    """Toggle sleep for the whole worker via the single global kill switch
    ``engines.vllm.disable_sleep_mode`` (and force-disable prefix caching for
    benchmark models).

    Sleep is governed by ONE global flag rather than a per-model
    ``enable_sleep_mode`` override on every capabilities_model. Per-model
    overrides were error-prone: they polluted config.yml with N entries, a
    force-killed run left them behind, and the unconditional config backup then
    captured the pollution as the restore baseline (stale ``enable_sleep_mode:
    false`` artifacts). The global flag is one line, wins over per-model values
    (see workernode model_can_sleep), and the benchmark's other config ops don't
    touch it — so it toggles cleanly: disable_sleep_mode=True for nosleep,
    =False for sleep. Any pre-existing per-model enable_sleep_mode overrides are
    stripped so they can't block the global decision.

    Prefix caching is always disabled for benchmark models (enable_prefix_caching
    = False) regardless of `enabled`, so every request does a full prefill and the
    latency/energy numbers are fair and reproducible.

    Requires pyyaml (the sed fallback can't safely edit nested YAML).
    """
    sudo = "sudo " if use_sudo else ""
    config_path = f"{workernode_dir}/config.yml"
    if not _YAML:
        raise RuntimeError("pyyaml is required to manage sleep mode (engines.vllm.disable_sleep_mode).")

    for host in hosts:
        read_res = subprocess.run(
            _build_ssh_cmd(host, ssh_user, ssh_key, f"cat {shlex.quote(config_path)}", relay_host, relay_user),
            capture_output=True,
            text=True,
        )
        if read_res.returncode != 0:
            raise RuntimeError(f"Cannot read config.yml on {host}: {read_res.stderr.strip()}")

        cfg = _yaml.safe_load(read_res.stdout) or {}
        models = [m.get("model", "") for m in cfg.get("logos", {}).get("capabilities_models", []) if m.get("model")]
        vllm_cfg = cfg.setdefault("engines", {}).setdefault("vllm", {})
        # The global kill switch is the single source of truth for sleep.
        vllm_cfg["disable_sleep_mode"] = not enabled
        model_overrides = vllm_cfg.setdefault("model_overrides", {})
        for model in models:
            ov = model_overrides.setdefault(model, {})
            # Strip any stale per-model sleep override so only the global flag governs.
            ov.pop("enable_sleep_mode", None)
            # Prefix caching always off for benchmark runs (fair, reproducible
            # full-prefill latency/energy; no cross-request KV reuse).
            ov["enable_prefix_caching"] = False

        new_config = _yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False)
        write_res = subprocess.run(
            _build_ssh_cmd(
                host,
                ssh_user,
                ssh_key,
                f"{sudo}tee {shlex.quote(config_path)} > /dev/null",
                relay_host,
                relay_user,
            ),
            input=new_config.encode(),
            capture_output=True,
        )
        if write_res.returncode != 0:
            raise RuntimeError(f"Cannot write config.yml on {host}: {write_res.stderr.decode().strip()}")
        print(
            f"  [logos] {host}: Set engines.vllm.disable_sleep_mode={str(not enabled).lower()} "
            f"(sleep {'enabled' if enabled else 'disabled'}), enable_prefix_caching=false for {len(models)} models"
        )


def _set_logos_poll_intervals_via_ssh(
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    workernode_dir: str,
    gpu_poll_interval: int,
    status_refresh_interval_seconds: int,
    use_sudo: bool = True,
    relay_host: Optional[str] = None,
    relay_user: Optional[str] = None,
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
            print(f"  [logos] {host}: Set {key}={val} in {workernode_dir}/config.yml")
            result = subprocess.run(_build_ssh_cmd(host, ssh_user, ssh_key, remote_cmd, relay_host, relay_user))
            if result.returncode != 0:
                raise RuntimeError(f"Failed to patch {key} on {host} (exit {result.returncode}).")


def _stop_workernode_via_ssh(
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    workernode_dir: str,
    use_sudo: bool,
    relay_host: Optional[str] = None,
    relay_user: Optional[str] = None,
) -> None:
    """Stop the logos workernode on each GPU node via SSH docker compose down.

    Before tearing the container down, dump its full docker logs to
    ``{workernode_dir}/saved_logs/worker-<UTC timestamp>.log`` on the GPU host so
    the worker-side record survives container removal (e.g. when the ollama
    scenario replaces it) and can be analyzed after the run.
    """
    sudo = "sudo " if use_sudo else ""
    save_dir = f"{workernode_dir}/saved_logs"
    # Save logs first, then bring the workernode down. The log dump is best-effort
    # (|| true) so a logging hiccup never blocks the teardown.
    dump = shlex.quote(
        f"docker compose logs --no-color --timestamps > " f"{save_dir}/worker-$(date -u +%Y%m%dT%H%M%SZ).log 2>&1"
    )
    remote_cmd = (
        f"cd {shlex.quote(workernode_dir)} && {sudo}mkdir -p {shlex.quote(save_dir)} && "
        f"{sudo}sh -c {dump} || true; "
        f"{sudo}docker compose down"
    )
    for host in hosts:
        print(f"  [logos] {host}: saving worker logs to {save_dir}/ then stopping")
        result = subprocess.run(_build_ssh_cmd(host, ssh_user, ssh_key, remote_cmd, relay_host, relay_user))
        if result.returncode != 0:
            raise RuntimeError(f"Failed to stop workernode on {host} (exit {result.returncode}).")
        print(f"  [logos] {host}: worker logs saved under {save_dir}/, workernode stopped.")


def _start_workernode_via_ssh(
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    workernode_dir: str,
    use_sudo: bool,
    relay_host: Optional[str] = None,
    relay_user: Optional[str] = None,
) -> None:
    """Start the logos workernode on each GPU node via SSH docker compose up -d.

    Does NOT pull images: the GPU nodes have no registry credentials for the
    root user (the deploy pipeline logs in as a different user), so a pull just
    fails and falls back to the local image anyway. Image updates are the deploy
    pipeline's job; the benchmark only starts what's already on the node.
    """
    sudo = "sudo " if use_sudo else ""
    remote_cmd = f"cd {shlex.quote(workernode_dir)} && {sudo}docker compose up -d"
    for host in hosts:
        print(f"  [logos] {host}: $ {remote_cmd}")
        result = subprocess.run(_build_ssh_cmd(host, ssh_user, ssh_key, remote_cmd, relay_host, relay_user))
        if result.returncode != 0:
            raise RuntimeError(f"Failed to start workernode on {host} (exit {result.returncode}).")
        print(f"  [logos] {host}: workernode started.")


def _stop_logos_workernodes_if_running_via_ssh(
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    workernode_dir: str,
    use_sudo: bool,
    relay_host: Optional[str] = None,
    relay_user: Optional[str] = None,
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
        print(f"  [ollama] {host}: Checking for running logos-workernode containers ...")
        subprocess.run(
            _build_ssh_cmd(host, ssh_user, ssh_key, remote_cmd, relay_host, relay_user)
        )  # non-fatal — best-effort only


# ── Benchmark config patching (filter models + disable RAM cache) ──────────


def _apply_benchmark_workernode_config_via_ssh(
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    workernode_dir: str,
    benchmark_models: list[str],
    local_cache_path: Optional[str],
    use_sudo: bool = True,
    relay_host: Optional[str] = None,
    relay_user: Optional[str] = None,
) -> None:
    """Back up config.yml and .env, then apply benchmark-only patches:

    config.yml: filter logos.capabilities_models to benchmark_models only.
    .env: set OLLAMA_MODELS_MOUNT to local_cache_path (if given), clear
          LOGOS_TMPFS_CACHE_PATH and TMPFS_SIZE=0 to disable the RAM pre-pop
          that otherwise fills 400 GB of RAM before any lane can start.
    """
    if not _YAML:
        print(
            "  [config] WARNING: pyyaml not installed — skipping capabilities_models filter.\n"
            "           Run: pip install pyyaml"
        )
    sudo = "sudo " if use_sudo else ""
    config_path = f"{workernode_dir}/config.yml"
    config_bak = f"{workernode_dir}/config.yml.benchmark_bak"
    env_path = f"{workernode_dir}/.env"
    env_bak = f"{workernode_dir}/.env.benchmark_bak"

    for host in hosts:
        # ── config.yml: read → filter capabilities_models → write back ────
        if _YAML:
            read_res = subprocess.run(
                _build_ssh_cmd(host, ssh_user, ssh_key, f"cat {shlex.quote(config_path)}", relay_host, relay_user),
                capture_output=True,
                text=True,
            )
            if read_res.returncode != 0:
                raise RuntimeError(f"  [config] {host}: Cannot read config.yml: {read_res.stderr.strip()}")

            # Non-destructive backup: only create .benchmark_bak if absent, so a
            # force-killed prior run can't overwrite the clean original baseline.
            _cp, _bak = shlex.quote(config_path), shlex.quote(config_bak)
            _bak_cmd = f"[ -f {_bak} ] || {sudo}cp {_cp} {_bak}"
            subprocess.run(
                _build_ssh_cmd(host, ssh_user, ssh_key, _bak_cmd, relay_host, relay_user),
                check=True,
            )

            cfg = _yaml.safe_load(read_res.stdout) or {}
            logos_cfg = cfg.setdefault("logos", {})
            orig_models = logos_cfg.get("capabilities_models", [])
            filtered = [m for m in orig_models if m.get("model", "") in benchmark_models]
            if not filtered:
                print(
                    f"  [config] {host}: WARNING: no benchmark models matched capabilities_models"
                    f" — keeping all {len(orig_models)}"
                )
                filtered = orig_models
            logos_cfg["capabilities_models"] = filtered

            removed = [m.get("model", "?") for m in orig_models if m.get("model", "") not in benchmark_models]
            kept = [m.get("model", "?") for m in filtered]
            new_config_yml = _yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False)

            write_res = subprocess.run(
                _build_ssh_cmd(
                    host,
                    ssh_user,
                    ssh_key,
                    f"{sudo}tee {shlex.quote(config_path)} > /dev/null",
                    relay_host,
                    relay_user,
                ),
                input=new_config_yml.encode(),
                capture_output=True,
            )
            if write_res.returncode != 0:
                raise RuntimeError(f"  [config] {host}: Cannot write config.yml: {write_res.stderr.decode().strip()}")
            if removed:
                print(f"  [config] {host}: capabilities_models: kept {kept}, disabled {removed}")

        # ── .env: read → disable RAM cache → optionally set local model path ──
        env_res = subprocess.run(
            _build_ssh_cmd(host, ssh_user, ssh_key, f"cat {shlex.quote(env_path)}", relay_host, relay_user),
            capture_output=True,
            text=True,
        )
        if env_res.returncode != 0:
            print(f"  [config] {host}: No .env found — skipping RAM cache disable")
            continue

        subprocess.run(
            _build_ssh_cmd(
                host,
                ssh_user,
                ssh_key,
                f"[ -f {shlex.quote(env_bak)} ] || {sudo}cp {shlex.quote(env_path)} {shlex.quote(env_bak)}",
                relay_host,
                relay_user,
            ),
            check=True,
        )

        lines = env_res.stdout.splitlines()
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("LOGOS_TMPFS_CACHE_PATH="):
                new_lines.append("LOGOS_TMPFS_CACHE_PATH=")
            elif stripped.startswith("TMPFS_SIZE="):
                new_lines.append("TMPFS_SIZE=0")
            elif local_cache_path and stripped.startswith("OLLAMA_MODELS_MOUNT="):
                new_lines.append(f"OLLAMA_MODELS_MOUNT={local_cache_path}")
            else:
                new_lines.append(line)
        new_env = "\n".join(new_lines) + "\n"

        env_write_res = subprocess.run(
            _build_ssh_cmd(
                host,
                ssh_user,
                ssh_key,
                f"{sudo}tee {shlex.quote(env_path)} > /dev/null",
                relay_host,
                relay_user,
            ),
            input=new_env.encode(),
            capture_output=True,
        )
        if env_write_res.returncode != 0:
            raise RuntimeError(f"  [config] {host}: Cannot write .env: {env_write_res.stderr.decode().strip()}")
        msg = "disabled RAM cache (TMPFS_SIZE=0, LOGOS_TMPFS_CACHE_PATH=)"
        if local_cache_path:
            msg += f", OLLAMA_MODELS_MOUNT={local_cache_path}"
        print(f"  [config] {host}: .env: {msg}")


def _restore_benchmark_workernode_config_via_ssh(
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    workernode_dir: str,
    use_sudo: bool = True,
    relay_host: Optional[str] = None,
    relay_user: Optional[str] = None,
) -> None:
    """Restore config.yml and .env from benchmark backups on each GPU node."""
    sudo = "sudo " if use_sudo else ""
    for host in hosts:
        for fname, bak_name in [("config.yml", "config.yml.benchmark_bak"), (".env", ".env.benchmark_bak")]:
            orig = shlex.quote(f"{workernode_dir}/{fname}")
            bak = shlex.quote(f"{workernode_dir}/{bak_name}")
            restore_cmd = f"if [ -f {bak} ]; then {sudo}mv {bak} {orig} && echo restored; " f"else echo no_backup; fi"
            res = subprocess.run(
                _build_ssh_cmd(host, ssh_user, ssh_key, restore_cmd, relay_host, relay_user),
                capture_output=True,
                text=True,
            )
            if "restored" in res.stdout:
                print(f"  [config] {host}: Restored {fname}")
            elif "no_backup" in res.stdout:
                print(f"  [config] {host}: No backup for {fname} — skipping")
            else:
                print(f"  [config] {host}: Restore of {fname} may have failed (exit {res.returncode})")


async def _wait_for_tls(
    url: str,
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    timeout_s: float = 300.0,
    relay_host: Optional[str] = None,
    relay_user: Optional[str] = None,
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
        result = subprocess.run(
            _build_ssh_cmd(
                host,
                ssh_user,
                ssh_key,
                f"curl -s --max-time 5 -o /dev/null -w '%{{http_code}}' {shlex.quote(url)}",
                relay_host,
                relay_user,
            ),
            capture_output=True,
            text=True,
        )
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
    relay_host: Optional[str] = None,
    relay_user: Optional[str] = None,
) -> None:
    """Deploy docker-compose.yml for Ollama if not already present on the GPU node.

    Also ensures models_dir exists so Docker can bind-mount it without
    creating a root-owned directory on first run.
    """
    compose_file = f"{compose_dir}/docker-compose.yml"
    sudo = "sudo " if use_sudo else ""
    content = _ollama_compose_content(models_dir, local_models_dir)

    for host in hosts:
        # Check if compose file already exists
        check = subprocess.run(
            _build_ssh_cmd(host, ssh_user, ssh_key, f"test -f {shlex.quote(compose_file)}", relay_host, relay_user)
        )
        if check.returncode == 0:
            print(f"  [ollama] {host}: {compose_file} already present — skipping deploy.")
        else:
            print(f"  [ollama] {host}: Deploying docker-compose.yml to {compose_dir} ...")
            # Create directory and write file in one SSH round-trip via stdin pipe
            write_cmd = (
                f"{sudo}mkdir -p {shlex.quote(compose_dir)} && " f"{sudo}tee {shlex.quote(compose_file)} > /dev/null"
            )
            result = subprocess.run(
                _build_ssh_cmd(host, ssh_user, ssh_key, write_cmd, relay_host, relay_user),
                input=content.encode(),
            )
            if result.returncode != 0:
                raise RuntimeError(f"Failed to deploy docker-compose.yml to {host} (exit {result.returncode}).")
            print(f"  [ollama] {host}: docker-compose.yml deployed.")

        # Ensure the models directory exists (Docker bind-mount would create it
        # root-owned otherwise, causing permission issues for Ollama)
        mkdir_result = subprocess.run(
            _build_ssh_cmd(host, ssh_user, ssh_key, f"{sudo}mkdir -p {shlex.quote(models_dir)}", relay_host, relay_user)
        )
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
    relay_host: Optional[str] = None,
    relay_user: Optional[str] = None,
) -> None:
    """Start the Ollama container via docker compose on each GPU node."""
    sudo = "sudo " if use_sudo else ""
    remote_cmd = f"cd {shlex.quote(compose_dir)} && {sudo}docker compose up -d"
    for host in hosts:
        print(f"  [ollama] {host}: $ {remote_cmd}")
        result = subprocess.run(_build_ssh_cmd(host, ssh_user, ssh_key, remote_cmd, relay_host, relay_user))
        if result.returncode != 0:
            raise RuntimeError(f"Failed to start Ollama on {host} (exit {result.returncode}).")
        print(f"  [ollama] {host}: Ollama container started.")


def _stop_ollama_docker_via_ssh(
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    compose_dir: str,
    use_sudo: bool,
    relay_host: Optional[str] = None,
    relay_user: Optional[str] = None,
) -> None:
    """Stop and remove the Ollama container via docker compose on each GPU node."""
    sudo = "sudo " if use_sudo else ""
    remote_cmd = f"cd {shlex.quote(compose_dir)} && {sudo}docker compose down"
    for host in hosts:
        print(f"  [ollama] {host}: $ {remote_cmd}")
        result = subprocess.run(_build_ssh_cmd(host, ssh_user, ssh_key, remote_cmd, relay_host, relay_user))
        if result.returncode != 0:
            raise RuntimeError(f"Failed to stop Ollama on {host} (exit {result.returncode}).")
        print(f"  [ollama] {host}: Ollama container stopped.")


def _open_ssh_tunnel(
    host: str,
    ssh_user: str,
    ssh_key: Optional[str],
    local_port: int,
    remote_port: int,
    relay_host: Optional[str] = None,
    relay_user: Optional[str] = None,
) -> "subprocess.Popen[bytes]":
    """Open an SSH local-port-forward tunnel in the background.

    Forwards localhost:<local_port> on this machine to localhost:<remote_port>
    on <host>.  Use this to reach a service on a remote node that is not
    directly reachable over the network (e.g. Ollama on a GPU node behind a
    firewall).

    When relay_host is set, uses ProxyJump (-J) to route through the relay:
    Mac → relay → GPU node.  This is the correct approach for tunnels (nested
    SSH does not work for port forwards).

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
    if relay_host:
        parts += ["-J", f"{relay_user}@{relay_host}"]
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


def _ollama_tag_present(want: str, cached: set[str]) -> bool:
    """True only when the EXACT Ollama tag is already registered.

    A bare name (no ``:``) is treated as ``:latest`` on both sides. Matching is
    deliberately exact — NOT family-prefix — so that e.g. an existing
    ``gemma3:4b-it-qat`` does not mask a missing ``gemma3:12b-it-qat`` and cause
    a 404 at inference time (both share the ``gemma3`` base).
    """
    norm = lambda t: t if ":" in t else f"{t}:latest"  # noqa: E731
    want_norm = norm(want)
    return any(norm(c) == want_norm for c in cached)


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
        if _ollama_tag_present(model, cached):
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
    relay_host: Optional[str] = None,
    relay_user: Optional[str] = None,
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
    result = subprocess.run(
        _build_ssh_cmd(host, ssh_user, ssh_key, remote_cmd, relay_host, relay_user),
        capture_output=True,
        text=True,
    )
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
    relay_host: Optional[str] = None,
    relay_user: Optional[str] = None,
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
        if _ollama_tag_present(ollama_name, cached):
            print(f"  [ollama] '{ollama_name}': already registered — skipping local import.")
            continue
        if not hf_name:
            continue

        local_path = _find_model_local_path_via_ssh(
            host, ssh_user, ssh_key, hf_name, local_models_dir, relay_host, relay_user
        )
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
    provider_id: Optional[int] = None


async def _poll_model_states(
    logos_url: str,
    logos_key: str,
    t_start_mono: float,
    out: list,
    interval_s: float = 1.0,
    diag: Optional[dict] = None,
) -> None:
    """Background task: poll POST /logosdb/get_ollama_vram_stats every second and
    record per-(node, model) state from scheduler_signals.

    The endpoint returns *all* of today's snapshots on every call (it ignores the
    after_snapshot_id cursor), so we dedupe client-side by snapshot_id and only
    keep snapshots produced after this run started. Per-second granularity needs
    the workernode's logos.status_refresh_interval_seconds=1 (patched for the run);
    otherwise the underlying data is only as fine as that interval.

    ``diag`` (if given) collects polls/empty-polls/snapshot counts so the caller
    can warn when no data was produced (the timeline CSV is then written empty,
    making the gap visible rather than silently absent)."""
    import datetime as _dt

    t_start_wall = time.time()
    url = f"{logos_url.rstrip('/')}/logosdb/get_ollama_vram_stats"
    req_headers = {"logos_key": logos_key, "Content-Type": "application/json"}
    seen_ids: set[int] = set()
    polls = 0
    rows_seen = 0

    async with httpx.AsyncClient(verify=False, timeout=httpx.Timeout(10.0)) as client:
        # Bootstrap: mark every snapshot that already exists today as "seen" so we
        # don't backfill pre-run history (the endpoint always returns it).
        try:
            resp = await client.post(url, json={"after_snapshot_id": 0}, headers=req_headers)
            if resp.status_code == 200:
                for prov in resp.json().get("providers") or []:
                    for snap in prov.get("data") or []:
                        sid = snap.get("snapshot_id")
                        if sid is not None:
                            seen_ids.add(int(sid))
        except Exception:
            pass

        while True:
            await asyncio.sleep(interval_s)
            try:
                resp = await client.post(url, json={"after_snapshot_id": 0}, headers=req_headers)
                polls += 1
                if resp.status_code != 200:
                    continue
                data = resp.json()
                fresh = 0
                for prov in data.get("providers") or []:
                    pname = prov.get("name") or prov.get("base_url") or "unknown"
                    pid = prov.get("provider_id")
                    for snap in prov.get("data") or []:
                        sid = snap.get("snapshot_id")
                        if sid is not None:
                            if int(sid) in seen_ids:
                                continue
                            seen_ids.add(int(sid))
                        fresh += 1
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
                                    provider_id=int(pid) if pid is not None else None,
                                )
                            )
                rows_seen += fresh
            except Exception:
                pass
            finally:
                if diag is not None:
                    diag["polls"] = polls
                    diag["snapshots"] = rows_seen
                    diag["states"] = len(out)


def _write_model_timeline_csv(out_path: Path, snapshots: list) -> None:
    """Write per-node model-state time-series to CSV (header always written, even
    when empty, so a missing-data run is visible rather than silently absent)."""
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["t_offset_s", "provider_id", "provider", "model", "state"])
        w.writeheader()
        for s in snapshots:
            w.writerow(
                {
                    "t_offset_s": f"{s.t_offset_s:.3f}",
                    "provider_id": s.provider_id if s.provider_id is not None else "",
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

    # Single global average arrival rate: when --rps > 0 every pattern is
    # rescaled so each scenario offers the SAME mean load (rps req/s), differing
    # only in burstiness. Without this the per-pattern defaults each impose their
    # own (much heavier) rate — e.g. burst size=5/gap=1s = 5 req/s — regardless
    # of the intended offered load.
    rps: float = getattr(args, "rps", 0.0) or 0.0
    if rps > 0:
        # poisson: mean = lam/zeitraum → set mean to rps.
        poisson_lam, poisson_zeitraum_s = rps, 1.0
        # burst: burst_size requests every (burst_size / rps) s → mean = rps.
        inter_burst_delay_s = (burst_size / rps) if rps > 0 else inter_burst_delay_s
        # mixed runs 3 sub-streams concurrently; each must offer rps/3 so the
        # aggregate is rps. Handled at the mixed call site below.

    print(f"\nScenario : {scenario}")
    print(
        f"Pattern  : {traffic_pattern}  "
        + (f"(global rps={rps}/s) " if rps > 0 else "")
        + f"(burst: size={burst_size}, gap={inter_burst_delay_s:.3g}s | "
        f"poisson: λ={poisson_lam:.3g}/{poisson_zeitraum_s:.3g}s)"
    )
    print(f"Workload : {len(workload)} request(s) from '{workload_name}'")
    print(f"Target   : {base_url}")

    # Energy sources run simultaneously: a GPU tracker (NVIDIA driver) and/or the
    # Shelly wall-power tracker. Pass --shelly together with --gpu-host/--gpu-indices
    # to record BOTH GPU and wall energy for every request in one run.
    energy_sources: "dict[str, object]" = {}
    if args.gpu_host:
        ssh_key = args.gpu_ssh_key or _find_root_ssh_key()
        print(
            f"GPU      : SSH nvidia-smi (all GPUs) → {args.gpu_host}  "
            f"user={args.gpu_ssh_user}  key={ssh_key or '(none)'}"
        )
        _relay_h = getattr(args, "logos_ssh_host", None)
        _relay_u = (getattr(args, "logos_ssh_user", None) or getpass.getuser()) if _relay_h else None
        energy_sources["gpu"] = SshGpuTracker(
            hosts=args.gpu_host,
            ssh_user=args.gpu_ssh_user,
            ssh_key=ssh_key,
            poll_interval_ms=args.poll_interval_ms,
            relay_host=_relay_h,
            relay_user=_relay_u,
        )
    elif args.gpu_indices is not None:
        print(f"GPU      : local NVML  indices={args.gpu_indices}")
        energy_sources["gpu"] = GPUTracker(args.gpu_indices, args.poll_interval_ms)

    if getattr(args, "shelly", False):
        _transport = getattr(args, "shelly_transport", "udp")
        _ingest_file = getattr(args, "_shelly_ingest_file", None)
        if _transport == "http" and not _ingest_file:
            print("Wall     : Shelly http transport requested but no ingest sidecar — wall power disabled.")
        else:
            _where = f"file {_ingest_file}" if _transport == "http" else f"port {args.shelly_port}"
            print(f"Wall     : Shelly wall-power ({_transport}, {_where})")
            energy_sources["wall"] = ShellyTracker(
                port=args.shelly_port, transport=_transport, ingest_file=_ingest_file
            )

    if not energy_sources:
        # No source requested explicitly → default to local GPU index 0.
        print("GPU      : local NVML  indices=[0]")
        energy_sources["gpu"] = GPUTracker([0], args.poll_interval_ms)

    tracker = CompositeTracker(energy_sources)
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
    _poll_diag: dict = {}
    _poll_task: Optional[asyncio.Task] = None
    if logos_key is not None:
        _poll_task = asyncio.create_task(
            _poll_model_states(base_url, logos_key, t_run_start, state_snapshots, diag=_poll_diag)
        )

    # Pre-dispatch settle: when warmup is skipped, give the orchestrator's planner
    # a moment to start reacting before the first request hits a fully cold system.
    settle_s: float = getattr(args, "settle_delay_s", 0.0) or 0.0
    if settle_s > 0:
        print(f"  [settle] waiting {settle_s:.0f}s before first request ...", flush=True)
        await asyncio.sleep(settle_s)

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
        # Three sub-streams run concurrently; to keep the SCENARIO mean at rps,
        # each sub-stream offers rps/3. (Without --rps, fall back to the raw knobs.)
        if rps > 0:
            mixed_lam = rps / 3.0
            mixed_zeitraum_s = 1.0
            mixed_inter_burst_delay_s = burst_size / (rps / 3.0)
        else:
            mixed_lam, mixed_zeitraum_s = poisson_lam, poisson_zeitraum_s
            mixed_inter_burst_delay_s = inter_burst_delay_s
        results = await run_mixed(
            workload,
            base_url,
            logos_key,
            tracker,
            args.request_timeout_s,
            scenario,
            model_map,
            burst_size=burst_size,
            inter_burst_delay_s=mixed_inter_burst_delay_s,
            lam=mixed_lam,
            zeitraum_s=mixed_zeitraum_s,
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
            dispatch_rate=(poisson_lam / poisson_zeitraum_s if poisson_zeitraum_s else 1.0),
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
    # Authoritative scenario energy: integrate the power trace over the whole run
    # and attribute per-request/token by simple division (issue: per-request
    # windows over-count under concurrency).
    n_ok = summary["successful_requests"]
    n_tokens = summary["total_completion_tokens"]
    summary.update(_overall_energy_metrics(tracker, t_run_start, t_run_end, n_ok, n_tokens))

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.output_dir / f"{ts}_{scenario}_{workload_name}_{traffic_pattern}"
    out_dir.mkdir(parents=True, exist_ok=True)

    write_detailed(out_dir / "results_detailed.csv", results)
    write_summary(out_dir / "results_summary.csv", summary)
    _write_energy_timeline_csv(out_dir / "energy_timeline.csv", tracker, t_run_start, wall_s)
    generate_charts(out_dir, results, tracker, t_run_start)
    if logos_key is not None:
        # Always write the timeline CSV (even empty) so a missing-data run is
        # visible. The chart is only drawn when there are states to plot.
        _write_model_timeline_csv(out_dir / "model_timeline.csv", state_snapshots)
        if state_snapshots:
            _chart_model_timeline(out_dir / "chart_model_timeline.png", state_snapshots, wall_s)
        else:
            print(
                f"  [timeline] WARNING: no model-state snapshots captured "
                f"(polls={_poll_diag.get('polls', 0)}). The vram-stats endpoint returned no "
                f"new rows — check workernode logos.status_refresh_interval_seconds=1 and that "
                f"workers stayed connected.",
                file=sys.stderr,
            )

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
                "energy_sources": list(energy_sources.keys()),
                "shelly_enabled": bool(getattr(args, "shelly", False)),
                "energy_method": tracker.method,
                "total_wall_time_s": round(wall_s, 3),
                "request_count": len(results),
                # Reproducibility: traffic RNG seed (poisson/mixed timing) and the
                # workload's request→model assignment seed (from the CSV).
                "seed": getattr(args, "seed", None),
                "workload_seed": getattr(args, "workload_seed", None),
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

    # Scenario-level energy: integrated power over the run, divided by counts.
    measured = False
    for src, label in (("gpu", "GPU (NVIDIA driver)"), ("wall", "Wall (Shelly plug)")):
        total = summary.get(f"total_energy_{src}_j", math.nan)
        if math.isnan(total):
            continue
        measured = True
        per_req = summary.get(f"energy_per_request_{src}_j", math.nan)
        per_tok = summary.get(f"energy_per_token_{src}_mj", math.nan)
        print(
            f"  {label:<22}: total={total:.1f} J  "
            f"per-request={per_req:.2f} J  per-token={per_tok:.2f} mJ  (integrated/÷counts)"
        )
    if not measured:
        print("  Energy   : not measured (no GPU/Shelly samples)")

    print(f"  Results  : {out_dir}")
    print(f"{'='*58}")

    return summary


_TRAFFIC_PATTERNS = ["burst", "poisson", "sequential", "mixed"]


def _resolve_patterns(raw: Optional[str]) -> list[str]:
    """Resolve the --patterns selection (comma-separated) to canonical order.

    Empty/None → all four. Unknown names raise so a typo fails fast rather than
    silently running everything.
    """
    if not raw or not str(raw).strip():
        return list(_TRAFFIC_PATTERNS)
    wanted = [p.strip().lower() for p in str(raw).split(",") if p.strip()]
    if not wanted:
        raise ValueError(f"--patterns {raw!r} selected no patterns; valid: {_TRAFFIC_PATTERNS}")
    unknown = [p for p in wanted if p not in _TRAFFIC_PATTERNS]
    if unknown:
        raise ValueError(f"Unknown traffic pattern(s) {unknown}; valid: {_TRAFFIC_PATTERNS}")
    return [p for p in _TRAFFIC_PATTERNS if p in wanted]


_ALL_SCENARIOS = ["logos-nosleep", "ollama", "logos-sleep"]


def _resolve_scenarios(raw: Optional[str], only_ollama: bool) -> list[str]:
    """Resolve the --scenarios selection for --run-all-scenarios.

    only_ollama forces just ["ollama"]. Empty/None → all three. Unknown names
    raise so a typo fails fast. Used to limit a quick debug run to e.g.
    --scenarios logos-nosleep.
    """
    if only_ollama:
        return ["ollama"]
    if not raw or not str(raw).strip():
        return list(_ALL_SCENARIOS)
    wanted = [s.strip().lower() for s in str(raw).split(",") if s.strip()]
    if not wanted:
        raise ValueError(f"--scenarios {raw!r} selected no scenarios; valid: {_ALL_SCENARIOS}")
    unknown = [s for s in wanted if s not in _ALL_SCENARIOS]
    if unknown:
        raise ValueError(f"Unknown scenario(s) {unknown}; valid: {_ALL_SCENARIOS}")
    return [s for s in _ALL_SCENARIOS if s in wanted]


async def _run_all_traffic_patterns(
    scenario: str,
    base_url: str,
    logos_key: Optional[str],
    workload: list,
    workload_name: str,
    model_map: dict,
    args: argparse.Namespace,
) -> list:
    """Run the selected traffic patterns for a scenario; warmup is done only for the first.

    The set of patterns is ``--patterns`` (comma-separated; default all four), so a
    quick debug run can target a single pattern, e.g. ``--patterns mixed``.
    """
    selected = _resolve_patterns(getattr(args, "patterns", None))
    summaries = []
    for i, pattern in enumerate(selected):
        print(f"\n{'─' * 58}")
        print(f"  Traffic pattern {i+1}/{len(selected)}: {pattern.upper()}")
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


def _wipe_calibration_and_weights_via_ssh(
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    workernode_dir: str,
    weight_cache_path: Optional[str],
    use_sudo: bool,
    relay_host: Optional[str] = None,
    relay_user: Optional[str] = None,
) -> None:
    """Delete all calibration state AND downloaded model weights on each node.

    The workernode MUST be stopped before calling this (otherwise the container
    holds the files / GPU). Per node it removes:
      - ``{workernode_dir}/data/model_profiles.yml`` (+ ``.bak*``) — the
        calibration results that the worker reads to decide a model is
        "calibrated". Wiping these forces a fresh calibration on next start.
      - ``{workernode_dir}/data/calibration_logs/`` — the per-model logs plus
        the calibration black/whitelist files
        (``calibration_failed_commands.txt`` / ``calibration_succeeded_commands.txt``)
        and ``calibration_unsupported_models.txt``.
      - everything under the model weight cache (``weight_cache_path``, i.e. the
        ``OLLAMA_MODELS_MOUNT`` vLLM downloads into) so every model re-downloads
        from scratch. When ``weight_cache_path`` is not given it is read from
        ``{workernode_dir}/.env`` (``OLLAMA_MODELS_MOUNT``).
    """
    sudo = "sudo " if use_sudo else ""
    data_dir = shlex.quote(f"{workernode_dir}/data")
    env_path = shlex.quote(f"{workernode_dir}/.env")
    for host in hosts:
        parts = [
            f"{sudo}rm -f {data_dir}/model_profiles.yml {data_dir}/model_profiles.yml.bak*",
            f"{sudo}rm -rf {data_dir}/calibration_logs",
        ]
        if weight_cache_path:
            wp = shlex.quote(weight_cache_path.rstrip("/"))
            parts.append(
                f"{sudo}sh -c 'wp={wp}; "
                f'if [ -n "$wp" ] && [ "$wp" != "/" ]; then rm -rf "$wp"/* "$wp"/.[!.]* 2>/dev/null; fi; true\''
            )
            weight_note = f" + weights ({weight_cache_path})"
        else:
            parts.append(
                f'{sudo}sh -c \'wp=$(grep -E "^OLLAMA_MODELS_MOUNT=" {env_path} 2>/dev/null '
                f'| head -1 | cut -d= -f2- | tr -d \\"); '
                f'if [ -n "$wp" ] && [ "$wp" != "/" ]; then rm -rf "$wp"/* "$wp"/.[!.]* 2>/dev/null; fi; true\''
            )
            weight_note = " + weights (from .env OLLAMA_MODELS_MOUNT)"
        remote_cmd = " ; ".join(parts)
        print(f"  [calib] {host}: wiping calibration state + model weights ...")
        result = subprocess.run(_build_ssh_cmd(host, ssh_user, ssh_key, remote_cmd, relay_host, relay_user))
        if result.returncode != 0:
            raise RuntimeError(f"Failed to wipe calibration state on {host} (exit {result.returncode}).")
        print(f"  [calib] {host}: wiped profiles + calibration_logs{weight_note}.")


def _profile_is_calibrated(profile: object) -> bool:
    """Mirror the worker's own 'is this model calibrated?' test.

    Must match logos-workernode ``main._auto_calibrate_if_needed`` exactly so we
    stop waiting exactly when the worker would stop re-calibrating — and, just as
    importantly, so we do NOT treat as done a *legacy* calibrated profile the
    worker would itself recalibrate. If we were more lenient than the worker we
    would skip such a model, then fire requests the worker can't serve.

    A model counts as calibrated when:
      * not flagged ``calibration_unsupported`` (terminal — never serves, but it
        will never produce a profile either, so don't wait on it);
      * residency + sleep measurements are populated;
      * the KV envelope is not collapsed (min == max); and
      * for a ``calibrated`` profile: it carries kv_cache_to_max_model_len_pairs
        and is not in the old weights-only format (loaded_vram_mb sitting a full
        kv_budget above base_residency_mb).

    The worker's (tp, enforce_eager) provenance check is intentionally NOT
    mirrored here — it needs the per-model production plan from config; the
    workernode applies it on its own at calibration time.
    """
    if not isinstance(profile, dict):
        return False
    if profile.get("calibration_unsupported"):
        return True
    if profile.get("base_residency_mb") is None:
        return False
    # Sleep measurements (sleeping_residual_mb, sleep_l1_transient_host_ram_mb)
    # are N/A when the model won't sleep — the worker flags this via
    # sleep_mode_disabled. Requiring them for a nosleep model would loop forever
    # (a nosleep lane never produces a sleep measurement). Mirror the worker's
    # sleep_na guard so we don't wait on calibration the worker will never do.
    if not profile.get("sleep_mode_disabled"):
        for key in ("sleeping_residual_mb", "sleep_l1_transient_host_ram_mb"):
            if profile.get(key) is None:
                return False
    mn, mx = profile.get("min_kv_cache_mb"), profile.get("max_kv_cache_mb")
    if mn is not None and mx is not None and mn > 0 and mn == mx:
        return False  # collapsed KV envelope → worker re-calibrates
    if profile.get("residency_source") == "calibrated":
        # Legacy calibrated profile without the KV→max-model-len curve: the
        # worker recalibrates it ("missing kv_cache_to_max_model_len_pairs").
        if not profile.get("kv_cache_to_max_model_len_pairs"):
            return False
        # Old weights-only format: base stored weights-only, so loaded sits a
        # full kv_budget above base. New format stores full loaded VRAM.
        loaded = profile.get("loaded_vram_mb")
        kv_budget = profile.get("kv_budget_mb")
        base = profile.get("base_residency_mb")
        if loaded is not None and kv_budget is not None and base is not None and loaded - base > 0.5 * kv_budget:
            return False
    return True


def _calibration_status_for_host(
    host: str,
    ssh_user: str,
    ssh_key: Optional[str],
    profiles_path: str,
    unsupported_path: str,
    models: list[str],
    sudo: str,
    relay_host: Optional[str],
    relay_user: Optional[str],
) -> tuple[set[str], list[str]]:
    """Return (done, pending) benchmark models for one node from its profiles file."""
    unsupported: set[str] = set()
    r = subprocess.run(
        _build_ssh_cmd(
            host,
            ssh_user,
            ssh_key,
            f"{sudo}cat {shlex.quote(unsupported_path)} 2>/dev/null || true",
            relay_host,
            relay_user,
        ),
        capture_output=True,
        text=True,
    )
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            unsupported.add(line.split("\t")[0])

    r2 = subprocess.run(
        _build_ssh_cmd(
            host,
            ssh_user,
            ssh_key,
            f"{sudo}cat {shlex.quote(profiles_path)} 2>/dev/null || true",
            relay_host,
            relay_user,
        ),
        capture_output=True,
        text=True,
    )
    profiles: dict = {}
    if _YAML and (r2.stdout or "").strip():
        try:
            data = _yaml.safe_load(r2.stdout) or {}
            profiles = data.get("model_profiles") or {}
        except Exception:
            profiles = {}

    done: set[str] = set()
    pending: list[str] = []
    for model in models:
        if model in unsupported or _profile_is_calibrated(profiles.get(model)):
            done.add(model)
        else:
            pending.append(model)
    return done, pending


async def _wait_for_calibration_complete_via_ssh(
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    workernode_dir: str,
    benchmark_models: list[str],
    timeout_s: float,
    use_sudo: bool,
    relay_host: Optional[str] = None,
    relay_user: Optional[str] = None,
    poll_interval_s: float = 30.0,
) -> bool:
    """Poll every node's model_profiles.yml until all benchmark models calibrate.

    Calibration emits its progress only over the orchestrator event channel
    (no REST status endpoint), so we read the authoritative artifact instead:
    the profiles file each worker writes as it finishes a model. Returns True
    once every node has a complete (or unsupported) profile for every benchmark
    model, or False on timeout.
    """
    sudo = "sudo " if use_sudo else ""
    profiles_path = f"{workernode_dir}/data/model_profiles.yml"
    unsupported_path = f"{workernode_dir}/data/calibration_logs/calibration_unsupported_models.txt"
    models = list(benchmark_models)
    deadline = time.monotonic() + timeout_s
    print(
        f"\n[Calibration] Waiting for {len(models)} model(s) on {len(hosts)} node(s) "
        f"(timeout {timeout_s / 3600:.1f}h, polling every {poll_interval_s:.0f}s) ..."
    )
    while True:
        all_done = True
        print(f"  [calib] progress @ {time.strftime('%H:%M:%S')}:")
        for host in hosts:
            done, pending = _calibration_status_for_host(
                host, ssh_user, ssh_key, profiles_path, unsupported_path, models, sudo, relay_host, relay_user
            )
            line = f"    {host}: {len(done)}/{len(models)} done"
            if pending:
                line += f"  | pending: {', '.join(pending)}"
                all_done = False
            print(line)
        if all_done:
            print("[Calibration] All benchmark models calibrated on all nodes.")
            return True
        if time.monotonic() >= deadline:
            print("[Calibration] TIMEOUT — not all models calibrated in time.", file=sys.stderr)
            return False
        await asyncio.sleep(poll_interval_s)


async def _trigger_calibration_via_rest(
    logos_url: str,
    logos_key: str,
    provider_ids: list[int],
    admin_port: int = 9443,
    connect_timeout_s: float = 900.0,
) -> bool:
    """Start a calibration session on each provider via the admin REST endpoint.

    The deployed worker does NOT auto-calibrate on startup — it parks in
    ZERO-LANE mode until the orchestrator tells it to. We trigger it explicitly
    with ``POST /logosdb/providers/logosnode/calibrate_uncalibrated``, which is
    served on the admin port (9443), NOT the user-facing logos_url (443). The
    endpoint returns 503 until the worker has connected and sent its first
    status, so each provider is retried until it accepts the session.

    Returns True iff a session was started for every provider.
    """
    host = logos_url.split("://")[-1].split("/")[0].split(":")[0]
    endpoint = f"https://{host}:{admin_port}/logosdb/providers/logosnode/calibrate_uncalibrated"
    all_ok = True
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        for pid in provider_ids:
            deadline = time.monotonic() + connect_timeout_s
            started = False
            while True:
                try:
                    r = await client.post(endpoint, json={"provider_id": pid, "logos_key": logos_key})
                    if r.status_code == 200:
                        try:
                            msg = r.json().get("message", "calibration session started")
                        except Exception:
                            msg = "calibration session started"
                        print(f"  [calib] provider {pid}: {msg}")
                        started = True
                        break
                    if r.status_code != 503:  # 503 = worker not connected yet → keep retrying
                        print(
                            f"  [calib] provider {pid}: HTTP {r.status_code} {r.text[:200]}",
                            file=sys.stderr,
                        )
                except Exception as exc:
                    print(f"  [calib] provider {pid}: request error: {exc}", file=sys.stderr)
                if time.monotonic() >= deadline:
                    print(
                        f"  [calib] provider {pid}: worker not ready after {connect_timeout_s:.0f}s — giving up.",
                        file=sys.stderr,
                    )
                    break
                await asyncio.sleep(5.0)
            all_ok = all_ok and started
    return all_ok


async def _reset_and_calibrate_all_nodes(
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    workernode_dir: str,
    benchmark_models: list[str],
    weight_cache_path: Optional[str],
    calibration_timeout_s: float,
    logos_url: str,
    logos_key: str,
    provider_ids: list[int],
    admin_port: int,
    use_sudo: bool,
    relay_host: Optional[str] = None,
    relay_user: Optional[str] = None,
) -> bool:
    """Full from-scratch reset + calibration across all nodes simultaneously.

    1. Stop every workernode (free files + GPUs).
    2. Wipe calibration state + downloaded weights on every node.
    3. Force ``enable_sleep_mode=true`` for all benchmark models — the worker's
       calibration *skips* any sleep-disabled model (the sleep gate in
       logos_bridge._run_calibration_session), so without this every model
       would be skipped and never calibrate.
    4. Start all nodes at once, then trigger a calibration session on every
       provider via REST. Each worker walks its uncalibrated models (the
       sessions run in parallel across nodes), re-downloading weights first.
    5. Block until all benchmark models are calibrated on all nodes.
    """
    print("\n" + "=" * 58)
    print("  [Reset+Calibrate] Full wipe and fresh calibration (all nodes)")
    print("=" * 58)
    _stop_workernode_via_ssh(hosts, ssh_user, ssh_key, workernode_dir, use_sudo, relay_host, relay_user)
    _wipe_calibration_and_weights_via_ssh(
        hosts, ssh_user, ssh_key, workernode_dir, weight_cache_path, use_sudo, relay_host, relay_user
    )
    # Calibration needs sleep enabled to produce a complete profile.
    _set_logos_sleep_mode_via_ssh(
        hosts,
        ssh_user,
        ssh_key,
        workernode_dir,
        enabled=True,
        use_sudo=use_sudo,
        relay_host=relay_host,
        relay_user=relay_user,
    )
    print("\n[Reset+Calibrate] Starting all nodes ...")
    _start_workernode_via_ssh(hosts, ssh_user, ssh_key, workernode_dir, use_sudo, relay_host, relay_user)
    print(f"\n[Reset+Calibrate] Triggering calibration on provider(s) {provider_ids} (admin port {admin_port}) ...")
    if not await _trigger_calibration_via_rest(logos_url, logos_key, provider_ids, admin_port):
        print("  WARNING: could not start a calibration session on every provider.", file=sys.stderr)
    return await _wait_for_calibration_complete_via_ssh(
        hosts,
        ssh_user,
        ssh_key,
        workernode_dir,
        benchmark_models,
        calibration_timeout_s,
        use_sudo,
        relay_host,
        relay_user,
    )


def _reset_profile_entries_via_ssh(
    host: str,
    ssh_user: str,
    ssh_key: Optional[str],
    workernode_dir: str,
    models: list[str],
    use_sudo: bool,
    relay_host: Optional[str] = None,
    relay_user: Optional[str] = None,
) -> list[str]:
    """Delete specific model entries from one node's model_profiles.yml.

    The worker treats a model as calibrated the moment ``base_residency_mb`` is
    known — even if the sleep-residual measurement is missing (it was calibrated
    with sleep off, leaving ``sleeping_residual_mb: None``) — so it will NOT
    re-pick that model for calibration. The benchmark needs the COMPLETE profile
    (sleep scenarios size lanes from it), so we drop the entry to force a clean
    recalibration. The node must be stopped first, or the running worker
    re-saves the entry from memory. Reads/writes over SSH the same way as the
    config helpers (cat -> edit locally -> tee); needs pyyaml on this host.
    Returns the model names actually removed.
    """
    if not models:
        return []
    sudo = "sudo " if use_sudo else ""
    profiles_path = f"{workernode_dir}/data/model_profiles.yml"
    read_res = subprocess.run(
        _build_ssh_cmd(
            host,
            ssh_user,
            ssh_key,
            f"{sudo}cat {shlex.quote(profiles_path)} 2>/dev/null || true",
            relay_host,
            relay_user,
        ),
        capture_output=True,
        text=True,
    )
    if not (read_res.stdout or "").strip():
        print(f"  [calib] {host}: no profiles file to reset.")
        return []
    if not _YAML:
        # A profiles file exists with content but we cannot safely rewrite it
        # without pyyaml. Returning [] here would silently skip the reset and
        # leave models half-calibrated, defeating the recovery path — fail loud.
        raise RuntimeError(
            f"[calib] {host}: pyyaml is required to reset incomplete profile "
            f"entries {models}, but it is not installed. Install pyyaml on this "
            "host (the benchmark venv) and retry."
        )
    data = _yaml.safe_load(read_res.stdout) or {}
    mp = data.get("model_profiles") or {}
    removed = [m for m in models if mp.pop(m, None) is not None]
    if not removed:
        return []
    data["model_profiles"] = mp
    new_yaml = _yaml.safe_dump(data, default_flow_style=False)
    write_res = subprocess.run(
        _build_ssh_cmd(
            host,
            ssh_user,
            ssh_key,
            f"{sudo}tee {shlex.quote(profiles_path)} > /dev/null",
            relay_host,
            relay_user,
        ),
        input=new_yaml.encode(),
        capture_output=True,
    )
    if write_res.returncode != 0:
        raise RuntimeError(f"Cannot rewrite profiles on {host}: {write_res.stderr.decode().strip()}")
    print(f"  [calib] {host}: reset {len(removed)} incomplete profile(s): {', '.join(removed)}")
    return removed


async def _ensure_calibration_complete_all_nodes(
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    workernode_dir: str,
    benchmark_models: list[str],
    calibration_timeout_s: float,
    logos_url: str,
    logos_key: str,
    provider_ids: list[int],
    admin_port: int,
    use_sudo: bool,
    relay_host: Optional[str] = None,
    relay_user: Optional[str] = None,
) -> bool:
    """Finish calibration for any incomplete model WITHOUT wiping prior work.

    The full-reset path (:func:`_reset_and_calibrate_all_nodes`) is skipped when
    ``--reset-calibration`` is off, but the run must still guarantee every
    benchmark model is *completely* calibrated before firing traffic. Two failure
    modes this closes:

    * Never calibrated — the deployed worker parks in ZERO-LANE and does NOT
      auto-calibrate, so requests to it just fail.
    * Half-calibrated — the worker considers a model calibrated as soon as
      ``base_residency_mb`` is known, but a model calibrated with sleep OFF has
      ``sleeping_residual_mb: None``. The benchmark needs the full profile, so it
      counts that model uncalibrated — yet the worker will NOT re-pick it on its
      own. (This is exactly why two identical nodes can disagree: one calibrated
      a model with sleep on, the other with sleep off.)

    Order matters and mirrors the reset path:

    1. Read each node's profiles straight off disk (no worker needed — reading
       while a starting worker rewrites the file races). List the incomplete
       benchmark models per host. If none anywhere, re-using calibration is free.
    2. Stop the nodes (so the disk edits stick and the restart re-reads config),
       drop the incomplete entries so the worker actually re-picks them, and
       enable sleep mode (calibration *skips* sleep-disabled models AND needs
       sleep on to record the residual) — all while stopped.
    3. Start the nodes, trigger ``calibrate_uncalibrated`` on every provider, and
       block until every model has a complete profile.
    """
    sudo = "sudo " if use_sudo else ""
    profiles_path = f"{workernode_dir}/data/model_profiles.yml"
    unsupported_path = f"{workernode_dir}/data/calibration_logs/calibration_unsupported_models.txt"
    models = list(benchmark_models)

    # Read status from disk — the file exists whether or not the worker runs, and
    # reading it mid-startup-rewrite would catch a partial file.
    print("\n[Ensure-Calibrate] Checking calibration status on all nodes ...")
    pending_by_host: dict[str, list[str]] = {}
    pending_anywhere: set[str] = set()
    for host in hosts:
        done, pending = _calibration_status_for_host(
            host, ssh_user, ssh_key, profiles_path, unsupported_path, models, sudo, relay_host, relay_user
        )
        pending_by_host[host] = pending
        line = f"  [calib] {host}: {len(done)}/{len(models)} calibrated"
        if pending:
            line += f"  | incomplete: {', '.join(pending)}"
            pending_anywhere.update(pending)
        print(line)

    if not pending_anywhere:
        print("[Ensure-Calibrate] All benchmark models already calibrated on all nodes — nothing to do.")
        return True

    if not provider_ids:
        print(
            "  ERROR: models still need calibration "
            f"({', '.join(sorted(pending_anywhere))}) but no --calibration-provider-ids "
            "were given, so a session cannot be triggered. Pass them (or "
            "--reset-calibration) so the run can complete calibration first.",
            file=sys.stderr,
        )
        return False

    print("\n" + "=" * 58)
    print("  [Ensure-Calibrate] Finishing calibration for incomplete models")
    print("=" * 58)
    print(f"  Incomplete across nodes: {', '.join(sorted(pending_anywhere))}")

    # Stop first: profile edits would be overwritten by a running worker, and the
    # sleep-mode override is only read at startup.
    _stop_workernode_via_ssh(hosts, ssh_user, ssh_key, workernode_dir, use_sudo, relay_host, relay_user)

    # Drop the incomplete entries so the worker re-picks them (it would otherwise
    # skip a base_residency-only profile, treating it as already calibrated).
    for host in hosts:
        _reset_profile_entries_via_ssh(
            host, ssh_user, ssh_key, workernode_dir, pending_by_host[host], use_sudo, relay_host, relay_user
        )

    # Calibration needs sleep enabled to produce a complete profile.
    _set_logos_sleep_mode_via_ssh(
        hosts,
        ssh_user,
        ssh_key,
        workernode_dir,
        enabled=True,
        use_sudo=use_sudo,
        relay_host=relay_host,
        relay_user=relay_user,
    )

    print("\n[Ensure-Calibrate] Starting nodes ...")
    _start_workernode_via_ssh(hosts, ssh_user, ssh_key, workernode_dir, use_sudo, relay_host, relay_user)

    print(f"\n[Ensure-Calibrate] Triggering calibration on provider(s) {provider_ids} (admin port {admin_port}) ...")
    if not await _trigger_calibration_via_rest(logos_url, logos_key, provider_ids, admin_port):
        print("  WARNING: could not start a calibration session on every provider.", file=sys.stderr)
    return await _wait_for_calibration_complete_via_ssh(
        hosts,
        ssh_user,
        ssh_key,
        workernode_dir,
        models,
        calibration_timeout_s,
        use_sudo,
        relay_host,
        relay_user,
    )


async def _warmup_workernodes_sequentially(
    hosts: list[str],
    ssh_user: str,
    ssh_key: Optional[str],
    workernode_dir: str,
    logos_url: str,
    logos_key: Optional[str],
    workload: list,
    model_map: dict,
    scenario: str,
    warmup_timeout_s: float,
    use_sudo: bool,
    relay_host: Optional[str] = None,
    relay_user: Optional[str] = None,
) -> bool:
    """Pre-warm each GPU node by cycling workernodes one at a time.

    Each node is started in isolation so the Logos scheduler has no choice but
    to route every warmup request there — guaranteeing every benchmark model is
    downloaded to that node's local cache before the benchmark begins.  After all
    nodes have been cycled, all workernodes are restarted together for the actual
    benchmark run.

    Returns True iff every per-node warmup succeeded.
    """
    if not hosts:
        return True

    n = len(hosts)
    all_ok = True

    print(f"\n[Warmup pre-fetch] Cycling {n} node(s) one-by-one to pre-download all benchmark models ...")

    # Stop all nodes so the first one starts in full isolation.
    _stop_workernode_via_ssh(hosts, ssh_user, ssh_key, workernode_dir, use_sudo, relay_host, relay_user)

    for i, host in enumerate(hosts):
        print(f"\n  [{i + 1}/{n}] Pre-fetching models on {host} (other node(s) stopped) ...")
        _start_workernode_via_ssh([host], ssh_user, ssh_key, workernode_dir, use_sudo, relay_host, relay_user)

        if not await _wait_for_logos(logos_url, timeout_s=warmup_timeout_s, logos_key=logos_key):
            print(
                f"  [{i + 1}/{n}] WARNING: {host} did not connect in time — skipping model pre-fetch.",
                file=sys.stderr,
            )
            all_ok = False
            _stop_workernode_via_ssh([host], ssh_user, ssh_key, workernode_dir, use_sudo, relay_host, relay_user)
            continue

        ok = await _warmup(logos_url, logos_key, workload, scenario, model_map, timeout_s=warmup_timeout_s)
        if not ok:
            print(f"  [{i + 1}/{n}] WARNING: some models failed warmup on {host}.", file=sys.stderr)
            all_ok = False

        # Stop this node before starting the next so each node is isolated.
        if i < n - 1:
            print(f"  [{i + 1}/{n}] {host}: pre-fetch done — stopping before next node ...")
            _stop_workernode_via_ssh([host], ssh_user, ssh_key, workernode_dir, use_sudo, relay_host, relay_user)

    # The last node is still running.  Start all remaining nodes so the benchmark
    # has the full cluster.  Models are already cached — startup is fast.
    if n > 1:
        remaining = hosts[:-1]
        print(f"\n[Warmup pre-fetch] Starting remaining nodes to restore full cluster: {remaining} ...")
        _start_workernode_via_ssh(remaining, ssh_user, ssh_key, workernode_dir, use_sudo, relay_host, relay_user)
        if not await _wait_for_logos(logos_url, timeout_s=120.0, logos_key=logos_key):
            print("[Warmup pre-fetch] WARNING: not all workers reconnected after full restart.", file=sys.stderr)
            all_ok = False

    print(f"[Warmup pre-fetch] Complete — {n} node(s) have pre-downloaded all benchmark models.")
    return all_ok


async def _async_run_all(args: argparse.Namespace) -> None:
    """Orchestrate logos-nosleep → ollama → logos-sleep, managing services between runs."""
    only_ollama: bool = getattr(args, "only_ollama", False)
    if not only_ollama and not args.logos_key:
        print("Error: --logos-key is required for --run-all-scenarios (unless --only-ollama).", file=sys.stderr)
        sys.exit(1)
    if not args.gpu_host:
        print("Error: --gpu-host is required for --run-all-scenarios.", file=sys.stderr)
        sys.exit(1)
    if getattr(args, "reset_calibration", False) and not getattr(args, "calibration_provider_ids", None):
        print(
            "Error: --reset-calibration requires --calibration-provider-ids " "(e.g. '3 2' for deipapa deimama).",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.workload:
        workload = _load_csv(args.workload, model_override=args.model or None)
        workload_name = args.workload.stem
        args.workload_seed = _read_workload_seed(args.workload)
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
    logos_ssh_host: Optional[str] = getattr(args, "logos_ssh_host", None)
    logos_ssh_user: str = (getattr(args, "logos_ssh_user", None) or getpass.getuser()) if logos_ssh_host else ""
    relay_host = logos_ssh_host
    relay_user = logos_ssh_user or None
    # Defined early so _cleanup() can always reference them regardless of where
    # an abort occurs.
    ollama_host = args.gpu_host[:1]
    _tunnel_procs: list = []  # SSH port-forward processes opened during this run
    _benchmark_config_applied = [False]  # mutable flag so _cleanup can restore

    # Resolve the scenario selection up-front: all the Logos preamble (workernode
    # config patching, orchestrator Step 0, calibration) must run only when a
    # Logos scenario is actually selected. `--scenarios ollama` (without
    # --only-ollama) must NOT trigger any Logos bootstrap/calibration work.
    selected_scenarios = _resolve_scenarios(getattr(args, "scenarios", None), only_ollama)
    needs_logos = not only_ollama and any(s != "ollama" for s in selected_scenarios)

    # Suppress the orchestrator's nightly calibration window for the run so a
    # maintenance-window session can't fire mid-benchmark. Restored on teardown.
    manage_calib_window = getattr(args, "manage_calibration_window", True) and needs_logos
    _calib_window_disabled = [False]  # mutable flag so _cleanup can restore

    # Wall power over HTTPS/443: a Traefik-routed ingest sidecar this run manages.
    want_shelly_http = getattr(args, "shelly", False) and getattr(args, "shelly_transport", "udp") == "http"
    args._shelly_ingest_file = None  # set when the sidecar starts; read by _benchmark_scenario

    def _ensure_shelly_sidecar() -> None:
        if not want_shelly_http or args._shelly_ingest_file:
            return
        args._shelly_ingest_file = _start_shelly_ingest_sidecar(
            use_sudo, getattr(args, "shelly_ingest_image", "python:3-alpine")
        )

    def _cleanup(reason: str = "cleanup") -> None:
        """Best-effort stop of all containers/tunnels started by this run.

        Called on KeyboardInterrupt, CancelledError, or any unhandled exception
        so that GPU nodes are never left with dangling containers after an abort.
        All sub-calls are wrapped individually — one failure won't skip the rest.
        """
        print(f"\n  [{reason}] Stopping all containers and closing tunnels ...", file=sys.stderr)
        if _calib_window_disabled[0]:
            try:
                _set_calibration_window_enabled(
                    logos_dir,
                    enabled=True,
                    use_sudo=use_sudo,
                    relay_host=relay_host,
                    relay_user=relay_user,
                    ssh_key=ssh_key,
                )
                _calib_window_disabled[0] = False
            except Exception as _exc:
                print(f"  [{reason}] WARNING (restore calibration window): {_exc}", file=sys.stderr)
        if want_shelly_http:
            try:
                _stop_shelly_ingest_sidecar(use_sudo)
            except Exception as _exc:
                print(f"  [{reason}] WARNING (shelly sidecar stop): {_exc}", file=sys.stderr)
        for _p in list(_tunnel_procs):
            try:
                _close_ssh_tunnel(_p)
            except Exception:
                pass
        _tunnel_procs.clear()
        try:
            _stop_ollama_docker_via_ssh(
                ollama_host, args.gpu_ssh_user, ssh_key, ollama_compose_dir, use_sudo, relay_host, relay_user
            )
        except Exception as _exc:
            print(f"  [{reason}] WARNING (Ollama stop): {_exc}", file=sys.stderr)
        if getattr(args, "workernode_dir", None):
            try:
                _stop_workernode_via_ssh(
                    args.gpu_host, args.gpu_ssh_user, ssh_key, args.workernode_dir, use_sudo, relay_host, relay_user
                )
            except Exception as _exc:
                print(f"  [{reason}] WARNING (workernode stop): {_exc}", file=sys.stderr)
        if _benchmark_config_applied[0] and getattr(args, "workernode_dir", None):
            try:
                _restore_benchmark_workernode_config_via_ssh(
                    args.gpu_host, args.gpu_ssh_user, ssh_key, args.workernode_dir, use_sudo, relay_host, relay_user
                )
            except Exception as _exc:
                print(f"  [{reason}] WARNING (config restore): {_exc}", file=sys.stderr)

    # Unique Ollama model names this workload needs (via model map)
    unique_workload_models = list(dict.fromkeys(e.body["model"] for e in workload if e.body.get("model")))
    ollama_models_needed = list(
        dict.fromkeys(ollama_model_map[m] for m in unique_workload_models if m in ollama_model_map)
    )
    # Reverse map: ollama_name → hf_name (used for local path search)
    ollama_to_hf_map = {v: k for k, v in ollama_model_map.items()}

    # ── Pre-flight: apply benchmark-only workernode config ────────────────────
    if needs_logos and getattr(args, "workernode_dir", None):
        benchmark_local_cache: Optional[str] = getattr(args, "benchmark_local_cache", None)
        unique_logos_models = list(dict.fromkeys(e.body["model"] for e in workload if e.body.get("model")))
        print("\n[Pre-flight] Applying benchmark workernode config (filtering models, disabling RAM cache) ...")
        _apply_benchmark_workernode_config_via_ssh(
            args.gpu_host,
            args.gpu_ssh_user,
            ssh_key,
            args.workernode_dir,
            unique_logos_models,
            benchmark_local_cache,
            use_sudo,
            relay_host,
            relay_user,
        )
        _benchmark_config_applied[0] = True
        print("  (models will be downloaded on first warmup request per node)")

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

    if selected_scenarios != _ALL_SCENARIOS:
        print(f"  Scenarios      : {', '.join(selected_scenarios)}  (--scenarios filter)")

    try:
        if needs_logos:
            # ── Step 0: ensure orchestrator + Traefik are running ─────────────
            # We never tear down the orchestrator between scenarios because that
            # would also restart Traefik and lose the valid Let's Encrypt cert.
            # Workernodes reconnect to the already-running orchestrator when restarted.
            print("\n[Step 0] Ensuring Logos orchestrator is running ...")
            if relay_host:
                # logos_dir is a path on the relay/logos host — run docker compose there via SSH.
                _start_logos_via_ssh(str(logos_dir), relay_host, relay_user or "", ssh_key, use_sudo)
            else:
                _start_logos(logos_dir, use_sudo)  # docker compose up -d  (no-op if already running)

            # Disable the nightly calibration maintenance window for the run so a
            # window session can't fire mid-benchmark. Recreates only the
            # orchestrator (Traefik untouched), then the TLS wait below confirms
            # it is back up. Restored in _cleanup / on completion.
            if manage_calib_window:
                print("[Step 0] Disabling nightly calibration window for the run ...")
                _set_calibration_window_enabled(
                    logos_dir,
                    enabled=False,
                    use_sudo=use_sudo,
                    relay_host=relay_host,
                    relay_user=relay_user,
                    ssh_key=ssh_key,
                )
                _calib_window_disabled[0] = True

            # TLS check uses the admin entrypoint (port 9443): it is the only
            # entrypoint with a Host() rule in docker-compose, so Traefik always
            # serves the LE cert there. Workernodes also connect via 9443.
            _tls_host = logos_url.split("://")[-1].split("/")[0].split(":")[0]
            _tls_url = f"https://{_tls_host}:9443"
            if not await _wait_for_tls(
                _tls_url,
                args.gpu_host,
                args.gpu_ssh_user,
                ssh_key,
                timeout_s=300.0,
                relay_host=relay_host,
                relay_user=relay_user,
            ):
                print("  ERROR: Traefik did not obtain a valid TLS certificate — aborting.", file=sys.stderr)
                sys.exit(1)

            # Traefik is up — register the Shelly HTTPS ingest route (if requested).
            _ensure_shelly_sidecar()

            # ── Calibration: full reset, or just finish what's uncalibrated ──
            unique_logos_models = list(dict.fromkeys(e.body["model"] for e in workload if e.body.get("model")))
            if getattr(args, "reset_calibration", False):
                if not await _reset_and_calibrate_all_nodes(
                    args.gpu_host,
                    args.gpu_ssh_user,
                    ssh_key,
                    args.workernode_dir,
                    unique_logos_models,
                    getattr(args, "benchmark_local_cache", None),
                    getattr(args, "calibration_timeout", 86400.0),
                    logos_url,
                    args.logos_key,
                    args.calibration_provider_ids,
                    args.logos_admin_port,
                    use_sudo,
                    relay_host,
                    relay_user,
                ):
                    print(
                        "  WARNING: calibration did not fully complete — continuing anyway.",
                        file=sys.stderr,
                    )
            else:
                # Re-using prior calibration: still finish any model the deployed
                # worker never calibrated, or we'd just fire failing requests at it.
                if not await _ensure_calibration_complete_all_nodes(
                    args.gpu_host,
                    args.gpu_ssh_user,
                    ssh_key,
                    args.workernode_dir,
                    unique_logos_models,
                    getattr(args, "calibration_timeout", 86400.0),
                    logos_url,
                    args.logos_key,
                    getattr(args, "calibration_provider_ids", None) or [],
                    args.logos_admin_port,
                    use_sudo,
                    relay_host,
                    relay_user,
                ):
                    print(
                        "  WARNING: calibration did not fully complete — continuing anyway.",
                        file=sys.stderr,
                    )

            # ── Step 1: logos-nosleep ─────────────────────────────────────────
            if "logos-nosleep" in selected_scenarios:
                print("\n" + "─" * 58)
                print("[Step 1/3] logos-nosleep")
                print("─" * 58)
                _set_logos_sleep_mode_via_ssh(
                    args.gpu_host,
                    args.gpu_ssh_user,
                    ssh_key,
                    args.workernode_dir,
                    enabled=False,
                    use_sudo=use_sudo,
                    relay_host=relay_host,
                    relay_user=relay_user,
                )
                _set_logos_poll_intervals_via_ssh(
                    args.gpu_host,
                    args.gpu_ssh_user,
                    ssh_key,
                    args.workernode_dir,
                    gpu_poll_interval=1,
                    status_refresh_interval_seconds=1,
                    use_sudo=use_sudo,
                    relay_host=relay_host,
                    relay_user=relay_user,
                )
                if not args.skip_warmup and not await _warmup_workernodes_sequentially(
                    args.gpu_host,
                    args.gpu_ssh_user,
                    ssh_key,
                    args.workernode_dir,
                    logos_url,
                    args.logos_key,
                    workload,
                    {},
                    "logos-nosleep",
                    args.warmup_timeout,
                    use_sudo,
                    relay_host,
                    relay_user,
                ):
                    print("  WARNING: Per-node warmup had failures — continuing anyway.", file=sys.stderr)
                await _run_all_traffic_patterns(
                    "logos-nosleep", logos_url, args.logos_key, workload, workload_name, {}, args
                )
                print("\n  Stopping workernodes ...")
                _stop_workernode_via_ssh(
                    args.gpu_host, args.gpu_ssh_user, ssh_key, args.workernode_dir, use_sudo, relay_host, relay_user
                )

        if "ollama" in selected_scenarios:
            # ── Step 2: ollama ────────────────────────────────────────────────────
            step_label = "[Step 1/1] ollama" if only_ollama else "[Step 2/3] ollama"
            print("\n" + "─" * 58)
            print(step_label)
            print("─" * 58)
            if only_ollama:
                # No orchestrator Step 0 in this mode — try the ingest route now
                # (best-effort; works only if Traefik is already running persistently).
                _ensure_shelly_sidecar()
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
                    relay_host,
                    relay_user,
                )
            _deploy_ollama_compose_via_ssh(
                ollama_host,
                args.gpu_ssh_user,
                ssh_key,
                ollama_compose_dir,
                use_sudo,
                ollama_models_dir,
                ollama_local_models_dir,
                relay_host,
                relay_user,
            )
            _start_ollama_docker_via_ssh(
                ollama_host, args.gpu_ssh_user, ssh_key, ollama_compose_dir, use_sudo, relay_host, relay_user
            )

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
                relay_host=relay_host,
                relay_user=relay_user,
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
                        relay_host=relay_host,
                        relay_user=relay_user,
                    )
                    await _ensure_ollama_models(
                        tunnel_url, ollama_models_needed, timeout_per_model_s=args.warmup_timeout
                    )
                    await _run_all_traffic_patterns(
                        "ollama", tunnel_url, None, workload, workload_name, ollama_model_map, args
                    )
            finally:
                # Always stop the Ollama container and close the tunnel, even on abort.
                _stop_ollama_docker_via_ssh(
                    ollama_host, args.gpu_ssh_user, ssh_key, ollama_compose_dir, use_sudo, relay_host, relay_user
                )
                _close_ssh_tunnel(tunnel_proc)
                if tunnel_proc in _tunnel_procs:
                    _tunnel_procs.remove(tunnel_proc)

        if not only_ollama and "logos-sleep" in selected_scenarios:
            # ── Step 3: logos-sleep ───────────────────────────────────────────
            print("\n" + "─" * 58)
            print("[Step 3/3] logos-sleep")
            print("─" * 58)
            _set_logos_sleep_mode_via_ssh(
                args.gpu_host,
                args.gpu_ssh_user,
                ssh_key,
                args.workernode_dir,
                enabled=True,
                use_sudo=use_sudo,
                relay_host=relay_host,
                relay_user=relay_user,
            )
            _set_logos_poll_intervals_via_ssh(
                args.gpu_host,
                args.gpu_ssh_user,
                ssh_key,
                args.workernode_dir,
                gpu_poll_interval=1,
                status_refresh_interval_seconds=1,
                use_sudo=use_sudo,
                relay_host=relay_host,
                relay_user=relay_user,
            )
            if not await _warmup_workernodes_sequentially(
                args.gpu_host,
                args.gpu_ssh_user,
                ssh_key,
                args.workernode_dir,
                logos_url,
                args.logos_key,
                workload,
                {},
                "logos-sleep",
                args.warmup_timeout,
                use_sudo,
                relay_host,
                relay_user,
            ):
                print("  WARNING: Per-node warmup had failures — continuing anyway.", file=sys.stderr)
            await _run_all_traffic_patterns("logos-sleep", logos_url, args.logos_key, workload, workload_name, {}, args)
            print("\n  Stopping workernodes ...")
            _stop_workernode_via_ssh(
                args.gpu_host, args.gpu_ssh_user, ssh_key, args.workernode_dir, use_sudo, relay_host, relay_user
            )

        if _benchmark_config_applied[0]:
            print("\n[Post-run] Restoring original workernode config ...")
            _restore_benchmark_workernode_config_via_ssh(
                args.gpu_host, args.gpu_ssh_user, ssh_key, args.workernode_dir, use_sudo, relay_host, relay_user
            )
            _benchmark_config_applied[0] = False

        if want_shelly_http and args._shelly_ingest_file:
            _stop_shelly_ingest_sidecar(use_sudo)
            args._shelly_ingest_file = None

        if _calib_window_disabled[0]:
            print("\n[Post-run] Restoring nightly calibration window ...")
            _set_calibration_window_enabled(
                logos_dir,
                enabled=True,
                use_sudo=use_sudo,
                relay_host=relay_host,
                relay_user=relay_user,
                ssh_key=ssh_key,
            )
            _calib_window_disabled[0] = False

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
    p.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="Completion-token cap for --prompts mode. Default None = no limit "
        "(max_tokens omitted from the request so responses are never truncated).",
    )
    p.add_argument(
        "--interval-ms",
        type=float,
        default=0.0,
        help="Arrival offset between prompts in ms (--prompts mode).",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed for random traffic timing (poisson/mixed inter-arrivals). "
        "Recorded in run_meta.json alongside the workload's own seed so a run is "
        "1:1 reproducible.",
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

    # ── Shelly wall-power monitoring ─────────────────────────────────────────
    shelly_grp = p.add_argument_group(
        "Shelly wall-power monitoring",
        "shelly_daemon.py runs persistently on the Raspberry Pi and pushes UDP power "
        "readings to logos-test every second. Pass --shelly to listen for those packets. "
        "Measures total wall power (GPU + CPU + RAM) — more complete than nvidia-smi alone. "
        "ADDITIVE: combine --shelly with --gpu-host/--gpu-indices to record BOTH GPU "
        "(NVIDIA driver) and wall (Shelly) energy for every request in the same run; the "
        "detailed CSV then has separate energy_gpu_j and energy_wall_j columns.",
    )
    shelly_grp.add_argument(
        "--shelly",
        action="store_true",
        help="Enable Shelly wall-power monitoring (requires shelly_daemon.py running on the Pi). "
        "Can be combined with --gpu-host/--gpu-indices to measure GPU and wall power together.",
    )
    shelly_grp.add_argument(
        "--shelly-port",
        type=int,
        default=9876,
        metavar="PORT",
        help="Port the Pi pushes power readings to (default: 9876).",
    )
    shelly_grp.add_argument(
        "--shelly-transport",
        choices=["udp", "tcp", "http"],
        default="udp",
        help="Transport for Shelly readings; must match shelly_daemon.py. 'tcp' when the firewall "
        "drops inter-subnet UDP; 'http' when only HTTPS/443 passes — the pipeline starts a "
        "Traefik-routed ingest sidecar and the daemon POSTs to it (default: udp).",
    )
    shelly_grp.add_argument(
        "--shelly-ingest-image",
        default="python:3-alpine",
        metavar="IMAGE",
        help="Docker image for the http-transport ingest sidecar (needs python3). " "Default: python:3-alpine.",
    )

    # Warmup
    p.add_argument(
        "--warmup-timeout",
        type=float,
        default=3600.0,
        metavar="S",
        help="Seconds to wait for warmup responses before starting the benchmark. "
        "One request per unique model is sent concurrently. "
        "Cold-loading large models can take several minutes — keep this generous.",
    )
    p.add_argument(
        "--skip-warmup",
        action="store_true",
        help="Skip BOTH the per-node pre-fetch cycling and the per-scenario warmup "
        "(fast iteration; models cold-load on first real request).",
    )

    # Concurrency / timing
    p.add_argument(
        "--sequential",
        action="store_true",
        help="(Legacy) Send one request at a time in the sequential traffic pattern.",
    )
    p.add_argument("--max-concurrent", type=int, default=64)
    # Per-request client timeout. Defaults to the global LOGOS_TIMEOUT_S knob when
    # set (so one env var makes client + orchestrator agree on a ridiculous value
    # and no request times out client-side), else 600s.
    p.add_argument(
        "--request-timeout-s",
        type=float,
        default=float(os.getenv("LOGOS_TIMEOUT_S") or 600.0),
    )
    # Settle delay: with warmup skipped, dispatching the instant the run starts
    # hits a cold orchestrator before the planner has loaded any lane. Sleep this
    # many seconds after the run begins (and after model-state polling starts) but
    # before the first request, so the planner has a moment to react to demand.
    p.add_argument(
        "--settle-delay-s",
        type=float,
        default=0.0,
        metavar="S",
        help="Seconds to wait after the run starts before dispatching the first "
        "request. Useful when warmup is skipped. Default: 0.",
    )

    # Traffic patterns
    tp_grp = p.add_argument_group(
        "Traffic patterns",
        "Each scenario is run 4× with different traffic shapes: " "burst, Poisson, sequential, and mixed.",
    )
    tp_grp.add_argument(
        "--patterns",
        type=str,
        default=None,
        metavar="LIST",
        help="Comma-separated subset of traffic patterns to run "
        "(burst,poisson,sequential,mixed). Default: all four. "
        "E.g. --patterns mixed for a quick debug run.",
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
    tp_grp.add_argument(
        "--rps",
        type=float,
        default=0.0,
        metavar="R",
        help="Global average arrival rate (requests/second) that EVERY traffic "
        "pattern honours. When > 0 it overrides the per-pattern knobs so each "
        "scenario offers the same mean load, differing only in burstiness: "
        "sequential fires every 1/rps s; poisson has mean rps/s; burst fires "
        "--burst-size requests every burst_size/rps s; mixed splits its three "
        "concurrent sub-streams to aggregate to rps. Default: 0 (use the "
        "per-pattern knobs as-is).",
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
        "--scenarios",
        type=str,
        default=None,
        metavar="LIST",
        help="Comma-separated subset of scenarios to run with --run-all-scenarios "
        "(logos-nosleep,ollama,logos-sleep). Default: all three. "
        "E.g. --scenarios logos-nosleep for a quick debug run.",
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
        "--no-manage-calibration-window",
        dest="manage_calibration_window",
        action="store_false",
        default=True,
        help="Do NOT disable the orchestrator's nightly calibration window during the run. "
        "By default the benchmark sets LOGOS_CALIB_ENABLED=false (recreating only the "
        "orchestrator) for the run's duration and restores it afterwards, so a maintenance-"
        "window calibration session cannot fire mid-benchmark.",
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
    svc_grp.add_argument(
        "--logos-ssh-host",
        default=None,
        metavar="HOST",
        help="SSH relay host for all remote operations (e.g. logos-test.aet.cit.tum.de). "
        "Set this when running from a developer machine: Mac→relay (your key) then relay→GPU nodes (relay's key). "
        "Also used for the Logos docker compose commands (Step 0).",
    )
    svc_grp.add_argument(
        "--logos-ssh-user",
        default=None,
        metavar="USER",
        help="SSH username for --logos-ssh-host (default: current OS user). "
        "This is YOUR account on the relay, not logos-server.",
    )
    svc_grp.add_argument(
        "--benchmark-local-cache",
        default=None,
        metavar="DIR",
        help="Path on the GPU nodes to redirect OLLAMA_MODELS_MOUNT during the benchmark "
        "(e.g. /mnt/nvme/ollama_cache). When set, the benchmark config patch writes this "
        "path into .env so vLLM/Ollama uses local NVMe instead of Ceph. "
        "Omit to leave the existing OLLAMA_MODELS_MOUNT unchanged.",
    )
    svc_grp.add_argument(
        "--reset-calibration",
        action="store_true",
        help="Before any scenario: stop all workernodes, WIPE every node's "
        "calibration state (model_profiles.yml, calibration_logs/ incl. the "
        "failed/succeeded/unsupported black/whitelist) AND its downloaded model "
        "weights, then start all nodes at once with sleep enabled so each "
        "auto-calibrates from scratch in parallel, and wait until every "
        "benchmark model is calibrated before running. Re-downloads all weights "
        "— expect this to add hours. Use when stale calibration is mis-sizing "
        "lanes (e.g. KV cache starved to the floor).",
    )
    svc_grp.add_argument(
        "--calibration-timeout",
        type=float,
        default=86400.0,
        metavar="SECONDS",
        help="Max time to wait for --reset-calibration to finish on all nodes " "(default: 86400 = 24h).",
    )
    svc_grp.add_argument(
        "--calibration-provider-ids",
        type=int,
        nargs="+",
        default=None,
        metavar="ID",
        help="Provider IDs of the GPU worker nodes (e.g. '3 2' for deipapa deimama). "
        "Required with --reset-calibration, and used WITHOUT it too: every run "
        "triggers calibration for any model the worker never calibrated, and the "
        "calibrate trigger is per-provider (the orchestrator exposes no "
        "provider-listing endpoint reachable with a root key).",
    )
    svc_grp.add_argument(
        "--logos-admin-port",
        type=int,
        default=9443,
        metavar="PORT",
        help="Port for the orchestrator admin/logosnode REST endpoints "
        "(/logosdb/providers/logosnode/*). Default: 9443.",
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
        args.workload_seed = _read_workload_seed(args.workload)
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
    # Seed the RNG that drives poisson/mixed inter-arrival timing so the dispatch
    # schedule is reproducible; the workload's request→model mapping carries its
    # own seed (recorded in run_meta.json by _benchmark_scenario).
    random.seed(args.seed)
    print(f"  [seed] traffic RNG seeded with {args.seed}", flush=True)
    _raise_fd_limit()
    if args.run_all_scenarios:
        asyncio.run(_async_run_all(args))
    else:
        asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()

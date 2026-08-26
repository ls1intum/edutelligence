"""Host-RAM measurement helpers for the worker node.

The capacity planner on the Logos master treats host RAM as a first-class
resource axis parallel to VRAM. The worker measures each lane's host-RAM
footprint here so the master can make sleep-vs-stop eviction decisions that
account for the fact that vLLM sleep_l1/sleep_l2 retain weights in host RAM.

PSS (proportional set size) is the right metric: shared pages — like the
model weights mmapped across vLLM TP worker subprocesses — are counted once
across the tree rather than N times.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _on_macos() -> bool:
    """True when running on macOS, where /proc does not exist."""
    return sys.platform == "darwin"


def read_process_pss_mb(pid: int) -> float:
    """Read PSS in MiB from /proc/<pid>/smaps_rollup. Returns 0 on failure.

    On macOS there is no smaps_rollup and PSS is not reachable without private
    task-port APIs, so this reports 0 — which makes
    measure_process_tree_host_ram_mb fall through to RSS and label the result
    "rss" honestly, rather than returning an RSS number under a "pss" label.
    The loss is immaterial for the Metal backend: PSS exists here to avoid
    counting mmapped weights once per tensor-parallel rank, and Metal lanes are
    always single-process.
    """
    if _on_macos():
        return 0.0

    try:
        for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
            if line.startswith("Pss:"):
                parts = line.split()
                if len(parts) >= 2:
                    return float(parts[1]) / 1024.0
    except (FileNotFoundError, PermissionError, OSError, ValueError):
        return 0.0
    return 0.0


def read_process_rss_mb(pid: int) -> float:
    """Read VmRSS in MiB from /proc/<pid>/status. Returns 0 on failure."""
    if _on_macos():
        from logos_worker_node.metal import read_process_rss_mb as _rss  # noqa: PLC0415

        return _rss(pid)

    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                parts = line.split()
                if len(parts) >= 2:
                    return float(parts[1]) / 1024.0
    except (FileNotFoundError, PermissionError, OSError, ValueError):
        return 0.0
    return 0.0


def walk_process_tree(root_pid: int, max_pids: int = 256) -> set[int]:
    """Return {root_pid} ∪ all descendants discovered via /proc/<pid>/task/*/children.

    Capped at *max_pids* as a safety guard against /proc cycles or pathological
    forking. Returns an empty set if the root pid is gone.
    """
    if _on_macos():
        return _walk_process_tree_macos(root_pid, max_pids)
    if not Path(f"/proc/{root_pid}").exists():
        return set()
    visited: set[int] = set()
    to_visit: list[int] = [root_pid]
    while to_visit and len(visited) < max_pids:
        pid = to_visit.pop()
        if pid in visited:
            continue
        visited.add(pid)
        task_dir = Path(f"/proc/{pid}/task")
        if not task_dir.exists():
            continue
        try:
            tasks = list(task_dir.iterdir())
        except (FileNotFoundError, PermissionError, OSError):
            continue
        for tdir in tasks:
            children_file = tdir / "children"
            try:
                raw = children_file.read_text().split()
            except (FileNotFoundError, PermissionError, OSError):
                continue
            for token in raw:
                if not token.isdigit():
                    continue
                cpid = int(token)
                if cpid not in visited:
                    to_visit.append(cpid)
    return visited


def _walk_process_tree_macos(root_pid: int, max_pids: int) -> set[int]:
    """macOS process-tree walk via ``pgrep -P`` (no /proc to read)."""
    import subprocess  # noqa: PLC0415

    def _children(pid: int) -> list[int]:
        try:
            result = subprocess.run(
                ["pgrep", "-P", str(pid)], capture_output=True, text=True, timeout=5
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return []
        # pgrep exits 1 when there are simply no children — not an error.
        if result.returncode not in (0, 1):
            return []
        return [int(tok) for tok in result.stdout.split() if tok.isdigit()]

    # kill -0 probes existence without signalling; ESRCH means the pid is gone.
    try:
        os.kill(root_pid, 0)
    except ProcessLookupError:
        return set()
    except PermissionError:
        pass  # Alive, just not ours to signal.
    except OSError:
        return set()

    visited: set[int] = set()
    to_visit: list[int] = [root_pid]
    while to_visit and len(visited) < max_pids:
        pid = to_visit.pop()
        if pid in visited:
            continue
        visited.add(pid)
        to_visit.extend(cpid for cpid in _children(pid) if cpid not in visited)
    return visited


def measure_process_tree_host_ram_mb(root_pid: int) -> tuple[float, str]:
    """Return ``(mb, source)`` summed across the process tree rooted at *root_pid*.

    *source* is ``"pss"`` when /proc/<pid>/smaps_rollup yielded data for any
    process in the tree, ``"rss"`` when only /proc/<pid>/status was readable,
    and ``"unknown"`` otherwise.

    PSS is preferred because vLLM tensor-parallel workers share the model
    weights via mmap; summing RSS would multi-count those pages by TP size.
    """
    tree = walk_process_tree(root_pid)
    if not tree:
        return 0.0, "unknown"
    pss_total = 0.0
    pss_seen = False
    rss_total = 0.0
    for pid in tree:
        pss = read_process_pss_mb(pid)
        if pss > 0:
            pss_total += pss
            pss_seen = True
        rss_total += read_process_rss_mb(pid)
    if pss_seen and pss_total > 0:
        return pss_total, "pss"
    if rss_total > 0:
        return rss_total, "rss"
    return 0.0, "unknown"

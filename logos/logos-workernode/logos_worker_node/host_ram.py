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

from pathlib import Path


def read_process_pss_mb(pid: int) -> float:
    """Read PSS in MiB from /proc/<pid>/smaps_rollup. Returns 0 on failure."""
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

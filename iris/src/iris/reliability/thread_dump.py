"""Python-level thread dump that names the run behind every thread.

faulthandler writes at most 100 threads, newest first. In a stall there can be hundreds of
stuck threads and the one holding the lock is the oldest, so this dump lists threads with the
oldest run first and folds identical stacks into one entry with a count. It runs in Python,
which works while the stuck threads wait on a lock (they release the GIL).
"""

import gc
import os
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

import psutil

from iris.common.logging_config import get_logger
from iris.reliability.pools import PoolView
from iris.reliability.run_registry import RunRecord

logger = get_logger(__name__)

_KEEP_DUMPS = 20
_MAX_NAMES_PER_GROUP = 15


def _header(
    reason: str, pools: Iterable[PoolView], now: float, runs: list[RunRecord]
) -> list[str]:
    stats = gc.get_stats()
    lines = [
        f"Pyris thread dump {datetime.now(timezone.utc).isoformat()} pid={os.getpid()}",
        f"reason: {reason}",
        f"rss_bytes: {psutil.Process().memory_info().rss}",
        f"gc: enabled={gc.isenabled()} count={gc.get_count()} "
        f"threshold={gc.get_threshold()} "
        f"collections={[s.get("collections") for s in stats]}",
        f"threads: {threading.active_count()}  runs in flight: {len(runs)}",
        "pools (model id: lock held, open requests, connections):",
    ]
    for view in pools:
        lines.append(
            f"  {view.model_id}: {view.lock_held()}, {view.open_requests()}, "
            f"{view.connections()}"
        )
    lines.append("runs in flight (oldest first):")
    for record in sorted(runs, key=lambda r: r.started_at):
        lines.append(
            f"  run={record.run_id} pipeline={record.pipeline} variant={record.variant} "
            f"model={record.model_id} local={record.local} "
            f"age={now - record.started_at:.0f}s thread={record.thread_id} "
            f"phase={getattr(record.callback, "phase", None)}"
        )
    return lines


def format_thread_dump(
    reason: str,
    runs: list[RunRecord],
    pools: Iterable[PoolView] = (),
    first_thread_id: Optional[int] = None,
    now: Optional[float] = None,
) -> str:
    now = time.perf_counter() if now is None else now
    frames = sys._current_frames()  # pylint: disable=protected-access
    names = {thread.ident: thread.name for thread in threading.enumerate()}
    run_by_thread = {record.thread_id: record for record in runs}

    groups: dict[str, list[int]] = {}
    for thread_id, frame in frames.items():
        stack = "".join(traceback.format_stack(frame))
        groups.setdefault(stack, []).append(thread_id)

    def group_order(item: tuple[str, list[int]]) -> tuple[int, float, int]:
        thread_ids = item[1]
        if first_thread_id in thread_ids:
            return (0, 0.0, 0)
        starts = [run_by_thread[t].started_at for t in thread_ids if t in run_by_thread]
        if starts:
            return (1, min(starts), 0)
        return (2, 0.0, -len(thread_ids))

    lines = _header(reason, pools, now, runs)
    for stack, thread_ids in sorted(groups.items(), key=group_order):
        labels = []
        for thread_id in sorted(
            thread_ids,
            key=lambda t: run_by_thread[t].started_at if t in run_by_thread else now,
        ):
            record = run_by_thread.get(thread_id)
            label = f"{names.get(thread_id, "?")}({thread_id})"
            if record is not None:
                label += f" run={record.run_id} age={now - record.started_at:.0f}s"
            labels.append(label)
        shown = labels[:_MAX_NAMES_PER_GROUP]
        more = len(labels) - len(shown)
        lines.append("")
        lines.append(
            f"--- {len(thread_ids)} thread(s): {", ".join(shown)}"
            + (f" and {more} more" if more else "")
        )
        lines.append(stack.rstrip())
    return "\n".join(lines) + "\n"


def write_thread_dump(
    directory: str,
    reason: str,
    runs: list[RunRecord],
    pools_fn: Callable[[], list[PoolView]],
    first_thread_id: Optional[int] = None,
) -> Optional[Path]:
    """Write a dump file and log its name; returns None if the file could not be written."""
    try:
        pools = pools_fn()
    except Exception:  # pragma: no cover - diagnostics must not fail the caller
        logger.exception("Could not inspect the model connection pools")
        pools = []
    text = format_thread_dump(reason, runs, pools, first_thread_id)
    try:
        target_dir = Path(directory)
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        path = target_dir / f"threads-{stamp}.txt"
        path.write_text(text, encoding="utf-8")
        for old in sorted(target_dir.glob("threads-*.txt"))[:-_KEEP_DUMPS]:
            old.unlink(missing_ok=True)
    except OSError:
        logger.exception("Could not write the thread dump; logging it instead")
        logger.error("%s", text)
        return None
    logger.warning("Thread dump written to %s (reason: %s)", path, reason)
    return path

"""Restart Iris when a model client's connection pool stays locked.

On 2026-10-20 and 2026-10-22 a self-deadlock in one model client's httpcore pool (fixed in #1339)
made every chat request on that model hang without any error, until the process ran out of memory
hours later. This watchdog catches that state: a pool lock that is held in every sample over two
seconds, on two checks in a row (normally it is held for microseconds). It then logs a thread
dump, fails the open agent runs, sends an alert and exits, so Docker restarts Iris. At most one
restart per 30 minutes; after that it stays up and sends an urgent alert instead.
"""

import os
import sys
import tempfile
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait as wait_futures
from typing import Any, Callable, Optional

import requests

from iris.common.logging_config import get_logger

logger = get_logger(__name__)

CHECK_INTERVAL_SECONDS = 5.0
LOCK_SAMPLES = 10
LOCK_SAMPLE_INTERVAL_SECONDS = 0.2
MIN_RESTART_INTERVAL_SECONDS = 1800.0
FAIL_RUNS_BUDGET_SECONDS = 10.0
EXIT_TIMER_SECONDS = 60.0
EXIT_CODE = 70
# Survives the restart of the same container, which is what Docker's restart policy does.
LAST_RESTART_FILE = os.path.join(tempfile.gettempdir(), "pyris-watchdog-last-restart")
RESTART_MESSAGE = "Iris had to restart. Please try again."
PUSHOVER_URL = "https://api.pushover.net/1/messages.json"

# Callbacks of the agent runs in flight; failed before a restart so nobody waits for nothing.
_open_runs: set = set()
_open_runs_lock = threading.Lock()


def track_run(callback: Any) -> None:
    with _open_runs_lock:
        _open_runs.add(callback)


def untrack_run(callback: Any) -> None:
    with _open_runs_lock:
        _open_runs.discard(callback)


def model_pool_locks() -> dict[str, Any]:
    """The httpcore pool lock of every configured model client, read without taking it."""
    from iris.llm.llm_manager import (  # pylint: disable=import-outside-toplevel
        LlmManager,
    )

    locks = {}
    for entry in LlmManager().entries:
        http_client = getattr(getattr(entry, "_client", None), "_client", None)
        pool = getattr(getattr(http_client, "_transport", None), "_pool", None)
        lock = getattr(getattr(pool, "_optional_thread_lock", None), "_lock", None)
        if lock is not None:
            locks[entry.id] = lock
    return locks


def format_thread_dump() -> str:
    """All thread stacks, identical ones folded with a count (a stall has hundreds)."""
    names = {thread.ident: thread.name for thread in threading.enumerate()}
    groups: dict[str, list[str]] = {}
    for (
        thread_id,
        frame,
    ) in sys._current_frames().items():  # pylint: disable=protected-access
        stack = "".join(traceback.format_stack(frame))
        groups.setdefault(stack, []).append(names.get(thread_id, str(thread_id)))
    parts = []
    for stack, threads in sorted(groups.items(), key=lambda item: len(item[1])):
        parts.append(
            f"--- {len(threads)} thread(s): {", ".join(threads[:10])}\n{stack}"
        )
    return "\n".join(parts)


def send_alert(title: str, message: str, priority: int) -> None:
    """Pushover alert; priority -1 is quiet, 1 is urgent. Only logged without credentials."""
    name = os.environ.get("PYRIS_ALERT_NAME") or "pyris"
    logger.warning("Alert (priority %d): %s: %s | %s", priority, name, title, message)
    token = os.environ.get("PYRIS_PUSHOVER_APP_TOKEN")
    user = os.environ.get("PYRIS_PUSHOVER_USER_KEY")
    if not token or not user:
        return
    try:
        requests.post(
            PUSHOVER_URL,
            data={
                "token": token,
                "user": user,
                "title": f"{name}: {title}",
                "message": message[:1024],
                "priority": priority,
            },
            timeout=5,
        ).raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error("Could not send the alert: %s", e)


class Watchdog:
    """Background thread that checks the model pools and restarts a deadlocked Iris."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        locks_fn: Callable[[], dict[str, Any]] = model_pool_locks,
        alert_fn: Callable[[str, str, int], None] = send_alert,
        exit_fn: Callable[[int], Any] = os._exit,
        sleep_fn: Callable[[float], None] = time.sleep,
        last_restart_file: str = LAST_RESTART_FILE,
    ):
        self._locks_fn = locks_fn
        self._alert_fn = alert_fn
        self._exit_fn = exit_fn
        self._sleep_fn = sleep_fn
        self._last_restart_file = last_restart_file
        self._suspects: set[str] = set()

    def start(self) -> None:
        threading.Thread(target=self._run, name="pyris-watchdog", daemon=True).start()

    def _run(self) -> None:
        while True:
            self._sleep_fn(CHECK_INTERVAL_SECONDS)
            try:
                stuck = self.check()
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("Watchdog check failed")
                continue
            if stuck:
                self.trip(stuck)
                return

    def check(self) -> set[str]:
        """Models whose pool lock was held in every sample now and at the previous check."""
        locks = self._locks_fn()
        held = set(locks)
        for sample in range(LOCK_SAMPLES):
            held = {model for model in held if locks[model].locked()}
            if not held:
                break
            if sample < LOCK_SAMPLES - 1:
                self._sleep_fn(LOCK_SAMPLE_INTERVAL_SECONDS)
        stuck = held & self._suspects
        self._suspects = held
        return stuck

    def trip(self, stuck: set[str]) -> None:
        reason = f"connection pool lock stays held for {", ".join(sorted(stuck))}"
        logger.critical("Watchdog: %s\n%s", reason, format_thread_dump())
        if not self._restart_allowed():
            self._alert_fn(
                "broken, NOT restarting",
                f"{reason}. Restarted itself less than 30 min ago; restart it by hand.",
                1,
            )
            return
        # Whatever hangs below, the process goes.
        timer = threading.Timer(EXIT_TIMER_SECONDS, self._exit_fn, args=(EXIT_CODE,))
        timer.daemon = True
        timer.start()
        failed = self._fail_open_runs()
        self._alert_fn(
            "restarting itself", f"{reason}. Failed {failed} open run(s).", -1
        )
        self._exit_fn(EXIT_CODE)

    def _restart_allowed(self) -> bool:
        now = time.time()
        try:
            with open(self._last_restart_file, encoding="utf-8") as file:
                last: Optional[float] = float(file.read().strip())
        except (OSError, ValueError):
            last = None
        if last is not None and now - last < MIN_RESTART_INTERVAL_SECONDS:
            return False
        try:
            with open(self._last_restart_file, "w", encoding="utf-8") as file:
                file.write(str(now))
        except OSError:
            logger.exception("Could not record the restart")
        return True

    def _fail_open_runs(self) -> int:
        with _open_runs_lock:
            callbacks = list(_open_runs)
        if not callbacks:
            return 0
        executor = ThreadPoolExecutor(max_workers=16)
        futures = [
            executor.submit(callback.fail, RESTART_MESSAGE, code="restart")
            for callback in callbacks
        ]
        done, _ = wait_futures(futures, timeout=FAIL_RUNS_BUDGET_SECONDS)
        executor.shutdown(wait=False, cancel_futures=True)
        return sum(
            1 for future in done if future.exception() is None and future.result()
        )


watchdog = Watchdog()

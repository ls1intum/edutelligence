"""Watchdog thread: chat answer deadlines, Artemis keep-alive, stall detection, self-restart.

Every tick it
- fails chat runs that missed their answer deadline and closes runs whose answer went out but
  that never ended (each in its own helper thread, so a slow send never blocks the watchdog),
- re-sends RUNNING for quiet chat runs, so Artemis does not drop the job,
- writes a thread dump on request (``touch <diagnostics_dir>/dump-now`` or SIGUSR2),
- checks for direct signs that the process is broken. A slow model is not one of them: a restart
  does not help against it and would only kill in-flight work.

When the process is broken it trips once: it decides about the restart first (the restart history
must allow it), writes a thread dump, closes the open runs, alerts and exits so Docker restarts it.
"""

import faulthandler
import gc
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait as wait_futures
from pathlib import Path
from typing import Any, Callable, Optional

from iris.common.logging_config import get_logger
from iris.config import ReliabilitySettings, settings
from iris.reliability.alerts import QUIET, URGENT, send_alert
from iris.reliability.pools import PoolView, model_pools
from iris.reliability.restart_guard import (
    MARKER_CLEAN,
    MARKER_RUNNING,
    MARKER_WATCHDOG,
    RestartGuard,
)
from iris.reliability.run_registry import RunRecord, RunRegistry, run_registry
from iris.reliability.thread_dump import write_thread_dump
from iris.web.status.status_update import RunPhase

logger = get_logger(__name__)

DEADLINE_MESSAGE = "Iris did not finish the answer in time. Please try again."
DEADLINE_CODE = "timeout"
RESTART_MESSAGE = "Iris had to restart. Please try again."
RESTART_CODE = "restart"
STALLED_MESSAGE = (
    "Iris ran into a problem and could not finish the answer. Please try again."
)
STALLED_CODE = "stalled"
EXIT_CODE = 70

# A pool lock is held for microseconds per request. Held in every sample over two seconds, on
# two ticks in a row, means a thread will never release it.
_LOCK_SAMPLES = 10
_LOCK_SAMPLE_INTERVAL = 0.2
# Garbage collection counts as stopped when no collection ran for this long although the
# youngest generation is far above its threshold.
_GC_STALL_SECONDS = 60.0
_GC_THRESHOLD_FACTOR = 10
_LOOP_STALL_SECONDS = 30.0
_CLOSE_RUNS_WORKERS = 16
_CLOSE_RUNS_BUDGET_SECONDS = 30.0
_ANSWER_POST_POLL_SECONDS = 0.2
_ORPHAN_KEEP_SECONDS = 300.0
_RESTART_LOOP_COUNT = 3
_DUMP_TRIGGER = "dump-now"


def _gc_collections() -> int:
    return sum(generation.get("collections", 0) for generation in gc.get_stats())


class Watchdog:  # pylint: disable=too-many-instance-attributes
    """Background thread that enforces deadlines and restarts a broken process."""

    def __init__(
        self,
        config: ReliabilitySettings,
        registry: RunRegistry = run_registry,
        *,
        perf: Callable[[], float] = time.perf_counter,
        wall: Callable[[], float] = time.time,
        exit_fn: Callable[[int], Any] = os._exit,
        alert_fn: Callable[[str, str, int], bool] = send_alert,
        pools_fn: Callable[[], list[PoolView]] = model_pools,
        sample_sleep: Callable[[float], None] = time.sleep,
        gc_enabled: Callable[[], bool] = gc.isenabled,
        gc_youngest_count: Callable[[], int] = lambda: gc.get_count()[0],
        gc_youngest_threshold: Callable[[], int] = lambda: gc.get_threshold()[0],
        gc_collections: Callable[[], int] = _gc_collections,
    ):
        self._config = config
        self._registry = registry
        self._perf = perf
        self._wall = wall
        self._exit_fn = exit_fn
        self._alert_fn = alert_fn
        self._pools_fn = pools_fn
        self._sample_sleep = sample_sleep
        self._gc_enabled = gc_enabled
        self._gc_youngest_count = gc_youngest_count
        self._gc_youngest_threshold = gc_youngest_threshold
        self._gc_collections = gc_collections
        self._guard = RestartGuard(config)
        self._started_at = perf()
        self._stop = threading.Event()
        self._dump_requested = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop: Any = None
        self._loop_thread_id: Optional[int] = None
        self._loop_beat_at = perf()
        self._suspect_pools: set[str] = set()
        self._stuck_models: set[str] = set()
        self._warned_no_pools = False
        self._gc_last_collections: Optional[int] = None
        self._gc_stalled_since: Optional[float] = None
        self._tripped = False
        self._exiting = False
        self._faulthandler_file: Any = None
        self.healthy = True

    # Lifecycle -----------------------------------------------------------------------------

    def start(self, loop: Any = None) -> None:
        """Start from the event loop's thread (the main thread, for the signal handlers)."""
        if not self._config.enabled or self._thread is not None:
            return
        self._started_at = self._perf()
        self._loop = loop
        self._loop_thread_id = threading.get_ident()
        self._loop_beat_at = self._perf()
        self._on_process_start()
        self._install_signal_handlers()
        self._log_watched_pools()
        self._thread = threading.Thread(
            target=self._run, name="pyris-watchdog", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._config.enabled and not self._exiting:
            self._guard.write_marker(MARKER_CLEAN)

    def _run(self) -> None:
        while not self._stop.wait(self._config.tick_seconds):
            try:
                self.tick()
            except Exception:  # pragma: no cover - the watchdog itself must keep going
                logger.exception("Watchdog tick failed")

    def _on_process_start(self) -> None:
        marker = self._guard.read_marker()
        if marker == MARKER_RUNNING:
            count = self._guard.record_unexpected_restart(self._wall())
            if count >= _RESTART_LOOP_COUNT:
                self._alert_async(
                    "restart loop",
                    f"{count} unexpected restarts (OOM or kill) within "
                    f"{self._config.restart_min_interval_seconds / 60:.0f} min. "
                    "Needs a look.",
                    URGENT,
                )
            else:
                self._alert_async(
                    "unexpected restart",
                    "Pyris restarted without a clean shutdown (OOM or kill).",
                    QUIET,
                )
        self._guard.write_marker(MARKER_RUNNING)

    def _log_watched_pools(self) -> None:
        try:
            pools = self._pools_fn()
        except Exception:  # pragma: no cover - startup must not fail on diagnostics
            logger.exception("Could not inspect the model connection pools")
            return
        logger.info(
            "Watchdog started; watching %d connection pool(s): %s",
            len(pools),
            ", ".join(view.model_id for view in pools),
        )

    def _install_signal_handlers(self) -> None:
        try:
            if hasattr(signal, "SIGUSR2"):
                signal.signal(signal.SIGUSR2, lambda *_args: self._dump_requested.set())
            if hasattr(signal, "SIGUSR1"):
                directory = Path(self._config.diagnostics_dir)
                directory.mkdir(parents=True, exist_ok=True)
                # Fallback for a process that holds the GIL; at most 100 threads.
                self._faulthandler_file = open(  # pylint: disable=consider-using-with
                    directory / "faulthandler.txt", "a", encoding="utf-8"
                )
                faulthandler.register(
                    signal.SIGUSR1, file=self._faulthandler_file, all_threads=True
                )
        except (ValueError, OSError) as e:
            logger.warning("Could not install the diagnostics signal handlers: %s", e)

    # Tick ----------------------------------------------------------------------------------

    def tick(self) -> None:
        now = self._perf()
        # Each step on its own: one that fails must not keep the others, above all the
        # probes, from running.
        steps: tuple[tuple[Callable[..., None], tuple], ...] = (
            (self._check_runs, (now,)),
            (self._handle_dump_request, ()),
            (self._request_loop_beat, ()),
        )
        for step, args in steps:
            try:
                step(*args)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("Watchdog step %s failed", step.__name__)
        if self._tripped:
            return
        try:
            reason, first_thread_id = self._probe(now)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Watchdog probe failed")
            return
        if reason is not None:
            self._trip(reason, first_thread_id)

    def _check_runs(self, now: float) -> None:
        for record in self._registry.snapshot():
            callback = record.callback
            phase = getattr(callback, "phase", None)
            if record.orphaned and (
                (
                    phase is RunPhase.TERMINAL
                    and getattr(callback, "terminal_post_in_flight", False) is not True
                )
                # A caller that never sends its FAILED must not pin the run forever.
                or now - (record.orphaned_at or now) > _ORPHAN_KEEP_SECONDS
            ):
                self._registry.unregister(record)
                continue
            if record.action_in_flight or phase is None:
                continue
            if record.deadline_seconds is not None:
                if (
                    phase is RunPhase.RUNNING
                    and now - record.started_at > record.deadline_seconds
                ):
                    self._spawn(record, self._fail_after_deadline)
                    continue
                answer_sent_at = callback.answer_sent_at
                if (
                    phase is RunPhase.ANSWER_SENDING
                    and answer_sent_at is not None
                    and now - answer_sent_at > self._config.post_answer_grace_seconds
                    and not callback.answer_post_in_flight
                ):
                    self._spawn(record, self._finish_after_grace)
                    continue
            heartbeat_after = self._config.heartbeat_after_seconds
            if (
                record.is_chat
                and phase is RunPhase.RUNNING
                and callback.seconds_since_last_frame(now) > heartbeat_after
                and now - record.last_heartbeat_at > heartbeat_after
            ):
                record.last_heartbeat_at = now
                callback.watchdog_heartbeat()

    def _spawn(self, record: RunRecord, action: Callable[[RunRecord], None]) -> None:
        record.action_in_flight = True

        def run() -> None:
            try:
                action(record)
            finally:
                # Cleared even when the action lost a race (e.g. the answer went out first),
                # so a later check, such as the post-answer grace, still sees the run.
                record.action_in_flight = False

        try:
            threading.Thread(
                target=run, name="pyris-watchdog-action", daemon=True
            ).start()
        except RuntimeError:
            record.action_in_flight = False
            raise

    def _fail_after_deadline(self, record: RunRecord) -> None:
        logger.error(
            "Run %s (%s, model %s) missed its %.0f s answer deadline; failing it",
            record.run_id,
            record.pipeline,
            record.model_id,
            record.deadline_seconds,
        )
        record.callback.watchdog_fail(DEADLINE_MESSAGE, DEADLINE_CODE)

    def _finish_after_grace(self, record: RunRecord) -> None:
        logger.warning(
            "Run %s sent its answer but did not end within %.0f s; finishing it",
            record.run_id,
            self._config.post_answer_grace_seconds,
        )
        record.callback.watchdog_finish()

    def _handle_dump_request(self) -> None:
        trigger = Path(self._config.diagnostics_dir) / _DUMP_TRIGGER
        try:
            file_request = trigger.exists()
            if file_request:
                trigger.unlink(missing_ok=True)
        except OSError:
            file_request = False
        if file_request or self._dump_requested.is_set():
            self._dump_requested.clear()
            write_thread_dump(
                self._config.diagnostics_dir,
                "requested",
                self._registry.snapshot(),
                self._pools_fn,
            )

    def _request_loop_beat(self) -> None:
        if self._loop is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._loop_beat)
        except RuntimeError:  # loop closed during shutdown
            pass

    def _loop_beat(self) -> None:
        self._loop_beat_at = self._perf()

    # Probes --------------------------------------------------------------------------------

    def _probe(self, now: float) -> tuple[Optional[str], Optional[int]]:
        reason = self._probe_pool_locks()
        if reason is not None:
            return reason, None
        if now - self._started_at < self._config.startup_grace_seconds:
            return None, None
        reason = self._probe_gc(now)
        if reason is not None:
            return reason, None
        if self._loop is not None and now - self._loop_beat_at > _LOOP_STALL_SECONDS:
            return (
                f"event loop did not run for {now - self._loop_beat_at:.0f} s",
                self._loop_thread_id,
            )
        return None, None

    def _probe_pool_locks(self) -> Optional[str]:
        views = self._pools_fn()
        if not views and not self._warned_no_pools:
            self._warned_no_pools = True
            logger.warning(
                "Watchdog sees no model connection pool; the pool lock check is off "
                "(changed OpenAI/httpx internals?)"
            )
        held_every_time = {view.model_id: True for view in views}
        for sample in range(_LOCK_SAMPLES):
            for view in views:
                if held_every_time[view.model_id] and not view.lock_held():
                    held_every_time[view.model_id] = False
            if not any(held_every_time.values()):
                break
            if sample < _LOCK_SAMPLES - 1:
                self._sample_sleep(_LOCK_SAMPLE_INTERVAL)
        suspects = {model for model, held in held_every_time.items() if held}
        stuck = suspects & self._suspect_pools
        self._suspect_pools = suspects
        if stuck:
            self._stuck_models = stuck
            models = ", ".join(sorted(stuck))
            return f"connection pool lock stays held for {models}"
        return None

    def _probe_gc(self, now: float) -> Optional[str]:
        if not self._gc_enabled():
            self._gc_stalled_since = None
            return None
        collections = self._gc_collections()
        backlog = self._gc_youngest_count()
        far_above = backlog > _GC_THRESHOLD_FACTOR * self._gc_youngest_threshold()
        if collections != self._gc_last_collections or not far_above:
            self._gc_last_collections = collections
            self._gc_stalled_since = None
            return None
        if self._gc_stalled_since is None:
            self._gc_stalled_since = now
            return None
        if now - self._gc_stalled_since >= _GC_STALL_SECONDS:
            return (
                f"garbage collection stopped {now - self._gc_stalled_since:.0f} s ago "
                f"(youngest generation holds {backlog} objects)"
            )
        return None

    # Trip ----------------------------------------------------------------------------------

    def _trip(self, reason: str, first_thread_id: Optional[int]) -> None:
        self._tripped = True
        self.healthy = False
        logger.critical("Watchdog: process is broken: %s", reason)

        restart = (
            self._config.self_restart
            and self._guard.record_and_allow_self_restart(self._wall(), reason)
        )
        if restart:
            self._exiting = True
            self._registry.refusal = (RESTART_MESSAGE, RESTART_CODE)
            self._guard.write_marker(MARKER_WATCHDOG)
            timer = threading.Timer(
                self._config.exit_timer_seconds, self._exit_fn, args=(EXIT_CODE,)
            )
            timer.daemon = True
            timer.start()

        runs = self._registry.snapshot()
        dump = write_thread_dump(
            self._config.diagnostics_dir, reason, runs, self._pools_fn, first_thread_id
        )
        if restart:
            # Every run dies with the process; tell all of them.
            failed, finished = self._close_open_runs(
                runs, RESTART_MESSAGE, RESTART_CODE
            )
        else:
            # Iris stays up: runs on healthy models can still finish. Only a stuck pool
            # pins down its own runs; a stopped GC or event loop concerns all of them.
            if self._stuck_models:
                runs = [run for run in runs if run.model_id in self._stuck_models]
            failed, finished = self._close_open_runs(
                runs, STALLED_MESSAGE, STALLED_CODE
            )
        details = (
            f"{reason}. Closed {failed} open run(s) as failed, {finished} as finished. "
            f"Dump: {dump.name if dump else "not written"}."
        )
        if restart:
            self._alert_fn("restarting itself", details, QUIET)
            self._exit_fn(EXIT_CODE)
        else:
            self._alert_fn(
                "broken, NOT restarting",
                details
                + " Self-restart was refused (limit reached or history unusable). "
                "Restart it by hand.",
                URGENT,
            )

    def _close_open_runs(
        self, runs: list[RunRecord], message: str, code: str
    ) -> tuple[int, int]:
        # Leave a little of the budget for collecting the results.
        wait_until = time.monotonic() + _CLOSE_RUNS_BUDGET_SECONDS - 2

        def wait_while(still_sending: Callable[[], bool]) -> None:
            while still_sending() and time.monotonic() < wait_until:
                time.sleep(_ANSWER_POST_POLL_SECONDS)

        def close(record: RunRecord) -> str:
            callback = record.callback
            if getattr(callback, "phase", None) is RunPhase.RUNNING:
                if callback.watchdog_fail(message, code):
                    return "failed"
            # Read again: the answer may have started between the read above and the
            # failed claim, and then it has to land before the exit like any other.
            if getattr(callback, "phase", None) is RunPhase.ANSWER_SENDING:
                # An answer POST in flight must land before the exit, or the answer and the
                # run's end are lost: wait for it (bounded), then finish the run.
                wait_while(lambda: callback.answer_post_in_flight is True)
                if callback.watchdog_finish():
                    return "finished"
            # The pipeline's own terminal frame (possibly carrying an undelivered answer)
            # may still be on its way; let it land too.
            wait_while(
                lambda: getattr(callback, "terminal_post_in_flight", False) is True
            )
            if (
                getattr(callback, "answer_post_in_flight", False) is True
                or getattr(callback, "terminal_post_in_flight", False) is True
            ):
                logger.warning(
                    "Run %s: still sending when the close budget ran out", record.run_id
                )
            return "none"

        executor = ThreadPoolExecutor(
            max_workers=_CLOSE_RUNS_WORKERS, thread_name_prefix="pyris-watchdog-close"
        )
        try:
            # Fail the waiting students first: a slow answer POST below must not hold
            # the close workers while their runs queue behind it.
            ordered = sorted(
                runs,
                key=lambda r: getattr(r.callback, "phase", None)
                is not RunPhase.RUNNING,
            )
            futures = [executor.submit(close, record) for record in ordered]
            done, _ = wait_futures(futures, timeout=_CLOSE_RUNS_BUDGET_SECONDS)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        outcomes = [future.result() for future in done if future.exception() is None]
        return outcomes.count("failed"), outcomes.count("finished")

    def _alert_async(self, title: str, message: str, priority: int) -> None:
        threading.Thread(
            target=self._alert_fn,
            args=(title, message, priority),
            name="pyris-watchdog-alert",
            daemon=True,
        ).start()


watchdog = Watchdog(settings.reliability)

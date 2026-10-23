"""Watchdog: deadlines, keep-alive, the three stall probes, the trip sequence and restarts."""

# pylint: disable=protected-access,redefined-outer-name
import asyncio
import json
import threading
import time
from unittest.mock import MagicMock

import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.config import ReliabilitySettings  # noqa: E402
from iris.reliability.alerts import QUIET, URGENT  # noqa: E402
from iris.reliability.pools import PoolView  # noqa: E402
from iris.reliability.restart_guard import (  # noqa: E402
    MARKER_CLEAN,
    MARKER_RUNNING,
    MARKER_WATCHDOG,
    RestartGuard,
)
from iris.reliability.run_registry import (  # noqa: E402
    RunRecord,
    RunRegistry,
    chat_deadline_seconds,
)
from iris.reliability.watchdog import (  # noqa: E402
    DEADLINE_CODE,
    EXIT_CODE,
    RESTART_CODE,
    Watchdog,
)
from iris.web.status.status_update import ChatRunCallback, RunPhase  # noqa: E402


class Clock:
    """Fake clock that starts at the real perf_counter, so times the callbacks stamp
    themselves stay comparable to it on any machine."""

    def __init__(self, start=None):
        self.now = time.perf_counter() if start is None else start

    def __call__(self):
        return self.now


def _ok():
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    return response


def _callback():
    callback = ChatRunCallback(run_id="run-token", base_url="http://artemis")
    callback._post_status_payload = MagicMock(return_value=_ok())
    return callback


def _posted(callback):
    return [call.args[0] for call in callback._post_status_payload.call_args_list]


@pytest.fixture
def config(tmp_path):
    return ReliabilitySettings(diagnostics_dir=str(tmp_path / "diagnostics"))


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def registry():
    return RunRegistry()


def _watchdog(config, registry, clock, **overrides):
    kwargs = {
        "perf": clock,
        "wall": lambda: 1_800_000_000.0 + clock.now,
        "exit_fn": MagicMock(),
        "alert_fn": MagicMock(return_value=True),
        "pools_fn": lambda: [],
        "sample_sleep": lambda _seconds: None,
    }
    kwargs.update(overrides)
    watchdog = Watchdog(config, registry, **kwargs)
    # Run helper actions inline so the tests are deterministic.
    watchdog._spawn = lambda record, action: action(record)
    return watchdog


def _chat_run(registry, clock, callback, deadline=120.0):
    return registry.register(
        RunRecord(
            run_id="req-1",
            pipeline="ChatPipeline",
            variant="default",
            local=False,
            callback=callback,
            thread_id=threading.get_ident(),
            started_at=clock.now,
            deadline_seconds=deadline,
            model_id="gpt-6-luna-medium",
            is_chat=True,
            last_heartbeat_at=clock.now,
        )
    )


def test_deadlines_follow_variant_and_local_flag(config):
    assert chat_deadline_seconds(config, "default", False) == 120
    assert chat_deadline_seconds(config, "advanced", False) == 270
    assert chat_deadline_seconds(config, "default", True) == 360
    assert chat_deadline_seconds(config, "advanced", True) == 360


def test_a_run_past_its_deadline_is_failed_once(config, registry, clock):
    watchdog = _watchdog(config, registry, clock)
    callback = _callback()
    _chat_run(registry, clock, callback)

    clock.now += 119
    watchdog._check_runs(clock.now)
    assert callback.phase is RunPhase.RUNNING

    clock.now += 2
    watchdog._check_runs(clock.now)
    watchdog._check_runs(clock.now)

    failed = [p for p in _posted(callback) if p["runState"] == "FAILED"]
    assert len(failed) == 1
    assert failed[0]["error"]["code"] == DEADLINE_CODE


def test_a_slow_but_healthy_answer_is_left_alone(config, registry, clock):
    watchdog = _watchdog(config, registry, clock)
    callback = _callback()
    _chat_run(registry, clock, callback)

    clock.now += 85
    callback.send_result("the answer")
    callback._answer_sent_at = clock.now  # the callback stamps the real clock
    clock.now += 60
    watchdog._check_runs(clock.now)

    assert callback.phase is RunPhase.ANSWER_SENDING
    assert all(p["runState"] != "FAILED" for p in _posted(callback))


def test_a_run_that_never_ends_after_its_answer_is_finished_after_the_grace(
    config, registry, clock
):
    watchdog = _watchdog(config, registry, clock)
    callback = _callback()
    _chat_run(registry, clock, callback)
    callback.send_result("the answer")
    callback._answer_sent_at = clock.now

    clock.now += 119
    watchdog._check_runs(clock.now)
    assert callback.phase is RunPhase.ANSWER_SENDING

    clock.now += 2
    watchdog._check_runs(clock.now)
    assert callback.phase is RunPhase.TERMINAL
    assert _posted(callback)[-1]["runState"] == "FINISHED"


def test_a_quiet_chat_run_gets_a_heartbeat(config, registry, clock):
    watchdog = _watchdog(config, registry, clock)
    callback = _callback()
    callback._last_frame_at = clock.now
    _chat_run(registry, clock, callback, deadline=270)

    clock.now += 59
    watchdog._check_runs(clock.now)
    callback._drain_running_updates()
    assert {"runState": "RUNNING"} not in _posted(callback)

    clock.now += 2
    watchdog._check_runs(clock.now)
    watchdog._check_runs(clock.now)
    callback._drain_running_updates()
    assert _posted(callback).count({"runState": "RUNNING"}) == 1


def test_the_real_helper_thread_fails_the_run(config, registry, clock):
    watchdog = Watchdog(
        config, registry, perf=clock, pools_fn=lambda: [], alert_fn=MagicMock()
    )
    callback = _callback()
    _chat_run(registry, clock, callback)
    clock.now += 121

    watchdog._check_runs(clock.now)
    deadline = time.monotonic() + 5
    while callback.phase is not RunPhase.TERMINAL and time.monotonic() < deadline:
        time.sleep(0.01)

    assert callback.phase is RunPhase.TERMINAL


# Probes -------------------------------------------------------------------------------------


def test_a_pool_lock_held_on_two_checks_trips(config, registry, clock):
    lock = threading.Lock()
    pool = PoolView(model_id="gpt-6-luna-medium", pool=MagicMock(), lock=lock)
    watchdog = _watchdog(config, registry, clock, pools_fn=lambda: [pool])

    lock.acquire()
    try:
        assert watchdog._probe_pool_locks() is None
        reason = watchdog._probe_pool_locks()
    finally:
        lock.release()

    assert "gpt-6-luna-medium" in reason


def test_a_pool_lock_that_is_released_in_between_does_not_trip(config, registry, clock):
    lock = threading.Lock()
    pool = PoolView(model_id="gpt-6-luna-medium", pool=MagicMock(), lock=lock)
    watchdog = _watchdog(config, registry, clock, pools_fn=lambda: [pool])

    lock.acquire()
    assert watchdog._probe_pool_locks() is None
    lock.release()
    assert watchdog._probe_pool_locks() is None
    assert watchdog._probe_pool_locks() is None


def test_the_probe_watches_the_real_openai_pool_lock(config, registry, clock):
    from iris.llm.external.openai_chat import (  # pylint: disable=import-outside-toplevel
        DirectOpenAIChatModel,
    )
    from iris.reliability.pools import (  # pylint: disable=import-outside-toplevel
        _pool_of,
    )

    model = DirectOpenAIChatModel(
        id="gpt-6-luna-medium",
        type="openai_chat",
        model="gpt-test",
        api_key="sk-test",  # pragma: allowlist secret
        base_url="http://127.0.0.1:9/v1",
    )
    pool = _pool_of(model.get_client())
    view = PoolView(model_id=model.id, pool=pool, lock=pool._optional_thread_lock._lock)
    watchdog = _watchdog(config, registry, clock, pools_fn=lambda: [view])
    holding, release = threading.Event(), threading.Event()

    def hold_like_a_deadlocked_thread():
        with pool._optional_thread_lock:
            holding.set()
            release.wait(10)

    holder = threading.Thread(target=hold_like_a_deadlocked_thread, daemon=True)
    holder.start()
    assert holding.wait(5)
    try:
        assert watchdog._probe_pool_locks() is None
        assert "gpt-6-luna-medium" in watchdog._probe_pool_locks()
    finally:
        release.set()
        holder.join(5)


def _gc_watchdog(config, registry, clock, state):
    return _watchdog(
        config,
        registry,
        clock,
        gc_enabled=lambda: state["enabled"],
        gc_youngest_count=lambda: state["count"],
        gc_youngest_threshold=lambda: 2000,
        gc_collections=lambda: state["collections"],
    )


def test_stopped_garbage_collection_trips_after_a_minute(config, registry, clock):
    state = {"enabled": True, "count": 50_000, "collections": 7}
    watchdog = _gc_watchdog(config, registry, clock, state)

    assert watchdog._probe_gc(clock.now) is None
    clock.now += 5
    assert watchdog._probe_gc(clock.now) is None
    clock.now += 59
    assert watchdog._probe_gc(clock.now) is None
    clock.now += 2
    assert "garbage collection stopped" in watchdog._probe_gc(clock.now)


def test_collections_or_a_small_backlog_reset_the_gc_probe(config, registry, clock):
    state = {"enabled": True, "count": 50_000, "collections": 7}
    watchdog = _gc_watchdog(config, registry, clock, state)
    watchdog._probe_gc(clock.now)
    clock.now += 5
    watchdog._probe_gc(clock.now)

    clock.now += 50
    state["collections"] = 8
    assert watchdog._probe_gc(clock.now) is None
    clock.now += 61
    assert watchdog._probe_gc(clock.now) is None

    state["count"] = 100
    clock.now += 61
    assert watchdog._probe_gc(clock.now) is None


def test_disabled_gc_is_not_a_stall(config, registry, clock):
    state = {"enabled": False, "count": 50_000, "collections": 7}
    watchdog = _gc_watchdog(config, registry, clock, state)
    for _ in range(5):
        clock.now += 61
        assert watchdog._probe_gc(clock.now) is None


def test_gc_and_loop_probes_wait_for_the_startup_grace(config, registry, clock):
    state = {"enabled": True, "count": 50_000, "collections": 7}
    watchdog = _gc_watchdog(config, registry, clock, state)
    watchdog._loop = MagicMock()
    for _ in range(50):
        clock.now += 5
        assert watchdog._probe(clock.now) == (None, None)
    clock.now += 100
    reason, _ = watchdog._probe(clock.now)
    assert reason is not None


def test_a_stuck_event_loop_trips_and_names_the_loop_thread(config, registry, clock):
    watchdog = _watchdog(config, registry, clock)
    watchdog._loop = MagicMock()  # never runs the beat callback
    watchdog._loop_thread_id = 4242
    clock.now += config.startup_grace_seconds + 31

    reason, first_thread_id = watchdog._probe(clock.now)

    assert "event loop" in reason
    assert first_thread_id == 4242


def test_a_running_event_loop_keeps_beating(config, registry, clock):
    watchdog = _watchdog(config, registry, clock)
    loop = asyncio.new_event_loop()
    try:
        watchdog._loop = loop
        clock.now += config.startup_grace_seconds + 31
        watchdog._request_loop_beat()
        loop.run_until_complete(asyncio.sleep(0))
        assert watchdog._probe(clock.now) == (None, None)
    finally:
        loop.close()


# Trip ---------------------------------------------------------------------------------------


def test_trip_restarts_after_dump_closing_runs_and_a_quiet_alert(
    config, registry, clock
):
    exit_fn, alert_fn = MagicMock(), MagicMock(return_value=True)
    watchdog = _watchdog(config, registry, clock, exit_fn=exit_fn, alert_fn=alert_fn)
    callback = _callback()
    _chat_run(registry, clock, callback)

    watchdog._trip("connection pool lock stays held for gpt-6-luna-medium", None)

    exit_fn.assert_called_with(EXIT_CODE)
    assert watchdog.healthy is False
    title, message, priority = alert_fn.call_args.args
    assert "restarting" in title and priority == QUIET
    assert "Closed 1 open run(s) as failed" in message
    assert _posted(callback)[-1]["error"]["code"] == RESTART_CODE
    guard = RestartGuard(config)
    assert guard.read_marker() == MARKER_WATCHDOG
    assert list((config_dir := guard._dir).glob("threads-*.txt"))
    history = json.loads((config_dir / "restart-history.json").read_text())
    assert history[-1]["kind"] == "watchdog"


def test_trip_within_the_min_interval_stays_up_and_pages(config, registry, clock):
    guard = RestartGuard(config)
    assert guard.record_and_allow_self_restart(1_800_000_000.0 + clock.now - 600, "x")
    exit_fn, alert_fn = MagicMock(), MagicMock(return_value=True)
    watchdog = _watchdog(config, registry, clock, exit_fn=exit_fn, alert_fn=alert_fn)

    watchdog._trip("garbage collection stopped", None)

    exit_fn.assert_not_called()
    title, priority = alert_fn.call_args.args[0], alert_fn.call_args.args[2]
    assert "NOT restarting" in title and priority == URGENT
    assert watchdog.healthy is False


def test_the_trip_is_latched(config, registry, clock):
    alert_fn = MagicMock(return_value=True)
    lock = threading.Lock()
    pool = PoolView(model_id="m", pool=MagicMock(), lock=lock)
    watchdog = _watchdog(
        config,
        registry,
        clock,
        alert_fn=alert_fn,
        pools_fn=lambda: [pool],
        exit_fn=MagicMock(),
    )
    lock.acquire()
    try:
        for _ in range(4):
            watchdog.tick()
    finally:
        lock.release()

    assert alert_fn.call_count == 1


def test_an_unusable_restart_history_refuses_the_restart(config, registry, clock):
    guard = RestartGuard(config)
    guard._dir.mkdir(parents=True)
    (guard._dir / "restart-history.json").write_text("{not json")
    exit_fn, alert_fn = MagicMock(), MagicMock(return_value=True)
    watchdog = _watchdog(config, registry, clock, exit_fn=exit_fn, alert_fn=alert_fn)

    watchdog._trip("garbage collection stopped", None)

    exit_fn.assert_not_called()
    assert alert_fn.call_args.args[2] == URGENT


def test_the_hard_exit_timer_fires_when_a_step_hangs(tmp_path, registry, clock):
    config = ReliabilitySettings(
        diagnostics_dir=str(tmp_path / "diagnostics"), exit_timer_seconds=0.05
    )
    exited = threading.Event()
    hang = threading.Event()
    watchdog = _watchdog(
        config,
        registry,
        clock,
        exit_fn=lambda _code: exited.set(),
        alert_fn=lambda *_args: hang.wait(5),
    )
    tripper = threading.Thread(target=watchdog._trip, args=("stuck", None), daemon=True)
    tripper.start()
    try:
        assert exited.wait(2)
    finally:
        hang.set()
        tripper.join(5)


def test_no_self_restart_when_disabled(tmp_path, registry, clock):
    config = ReliabilitySettings(
        diagnostics_dir=str(tmp_path / "diagnostics"), self_restart=False
    )
    exit_fn = MagicMock()
    watchdog = _watchdog(config, registry, clock, exit_fn=exit_fn)

    watchdog._trip("stuck", None)

    exit_fn.assert_not_called()


# Process start and stop ---------------------------------------------------------------------


def test_start_after_a_kill_alerts_quietly(config, registry, clock):
    RestartGuard(config).write_marker(MARKER_RUNNING)
    alert_fn = MagicMock(return_value=True)
    watchdog = _watchdog(config, registry, clock, alert_fn=alert_fn)
    watchdog._alert_async = alert_fn

    watchdog._on_process_start()

    title, priority = alert_fn.call_args.args[0], alert_fn.call_args.args[2]
    assert "unexpected restart" in title and priority == QUIET
    assert RestartGuard(config).read_marker() == MARKER_RUNNING


def test_repeated_kills_page_as_a_restart_loop(config, registry, clock):
    guard = RestartGuard(config)
    for minutes_ago in (20, 10):
        guard.record_unexpected_restart(1_800_000_000.0 + clock.now - minutes_ago * 60)
    guard.write_marker(MARKER_RUNNING)
    alert_fn = MagicMock(return_value=True)
    watchdog = _watchdog(config, registry, clock, alert_fn=alert_fn)
    watchdog._alert_async = alert_fn

    watchdog._on_process_start()

    assert alert_fn.call_args.args[2] == URGENT


@pytest.mark.parametrize("marker", [None, MARKER_CLEAN, MARKER_WATCHDOG])
def test_planned_restarts_do_not_alert(config, registry, clock, marker):
    if marker is not None:
        RestartGuard(config).write_marker(marker)
    alert_fn = MagicMock(return_value=True)
    watchdog = _watchdog(config, registry, clock, alert_fn=alert_fn)
    watchdog._alert_async = alert_fn

    watchdog._on_process_start()

    alert_fn.assert_not_called()


def test_stop_leaves_the_clean_marker(config, registry, clock):
    watchdog = _watchdog(config, registry, clock)
    watchdog._on_process_start()

    watchdog.stop()

    assert RestartGuard(config).read_marker() == MARKER_CLEAN


def test_a_dump_request_file_writes_one_dump(config, registry, clock):
    watchdog = _watchdog(config, registry, clock)
    directory = RestartGuard(config)._dir
    directory.mkdir(parents=True)
    (directory / "dump-now").touch()

    watchdog._handle_dump_request()
    watchdog._handle_dump_request()

    assert not (directory / "dump-now").exists()
    assert len(list(directory.glob("threads-*.txt"))) == 1


def test_liveness_reflects_the_watchdog():
    from iris.reliability.watchdog import (  # pylint: disable=import-outside-toplevel
        watchdog,
    )
    from iris.web.routers.health.health_endpoint import (  # pylint: disable=import-outside-toplevel
        liveness,
    )

    try:
        watchdog.healthy = True
        assert asyncio.run(liveness()).status_code == 200
        watchdog.healthy = False
        assert asyncio.run(liveness()).status_code == 503
    finally:
        watchdog.healthy = True


# Review follow-ups --------------------------------------------------------------------------


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    return predicate()


def test_a_lost_race_at_the_deadline_still_gets_the_grace_finish(
    config, registry, clock
):
    """The answer goes out while the deadline fires; the run must not be ignored after."""
    watchdog = Watchdog(
        config, registry, perf=clock, pools_fn=lambda: [], alert_fn=MagicMock()
    )
    callback = _callback()
    record = _chat_run(registry, clock, callback)
    callback.send_result("the answer")  # pipeline wins the race
    clock.now += 121
    callback._answer_sent_at = clock.now - 1

    watchdog._check_runs(clock.now)  # nothing to do: the answer is on its way
    assert _wait_until(lambda: not record.action_in_flight)
    watchdog._fail_after_deadline(record)  # the lost race itself is harmless
    assert callback.phase is RunPhase.ANSWER_SENDING

    watchdog._spawn(record, watchdog._fail_after_deadline)
    assert _wait_until(lambda: not record.action_in_flight)
    clock.now += 121
    watchdog._check_runs(clock.now)

    assert _wait_until(lambda: callback.phase is RunPhase.TERMINAL)
    assert _posted(callback)[-1]["runState"] == "FINISHED"


def test_a_refused_restart_fails_only_runs_on_the_stuck_model(config, registry, clock):
    guard = RestartGuard(config)
    assert guard.record_and_allow_self_restart(1_800_000_000.0 + clock.now - 600, "x")
    lock = threading.Lock()
    pool = PoolView(model_id="gpt-6-luna-medium", pool=MagicMock(), lock=lock)
    alert_fn = MagicMock(return_value=True)
    watchdog = _watchdog(
        config, registry, clock, pools_fn=lambda: [pool], alert_fn=alert_fn
    )
    stuck_cb, healthy_cb = _callback(), _callback()
    _chat_run(registry, clock, stuck_cb)
    healthy = _chat_run(registry, clock, healthy_cb)
    healthy.model_id = "gpt-6.1-sol-medium"

    lock.acquire()
    try:
        watchdog.tick()
        watchdog.tick()
    finally:
        lock.release()

    assert stuck_cb.phase is RunPhase.TERMINAL
    assert _posted(stuck_cb)[-1]["error"]["code"] == "stalled"
    assert healthy_cb.phase is RunPhase.RUNNING
    assert "Closed 1 open run(s) as failed" in alert_fn.call_args.args[1]


def test_runs_that_could_not_be_closed_are_not_counted(config, registry, clock):
    watchdog = _watchdog(config, registry, clock)
    callback = _callback()
    _chat_run(registry, clock, callback)
    callback.finish()  # already terminal: watchdog_fail returns False

    failed, finished = watchdog._close_open_runs(registry.snapshot(), "message", "code")

    assert (failed, finished) == (0, 0)


def test_a_failing_step_does_not_stop_the_probes(config, registry, clock):
    lock = threading.Lock()
    pool = PoolView(model_id="m", pool=MagicMock(), lock=lock)
    watchdog = _watchdog(config, registry, clock, pools_fn=lambda: [pool])
    watchdog._check_runs = MagicMock(side_effect=RuntimeError("can't start thread"))
    watchdog._check_runs.__name__ = "_check_runs"

    lock.acquire()
    try:
        watchdog.tick()
        watchdog.tick()
    finally:
        lock.release()

    assert watchdog.healthy is False


def test_heartbeat_gives_up_when_the_update_lock_is_busy():
    callback = _callback()
    callback._running_update_lock.acquire()
    try:
        started = time.monotonic()
        assert callback.watchdog_heartbeat() is False
        assert time.monotonic() - started < 3
    finally:
        callback._running_update_lock.release()
    assert callback.watchdog_heartbeat() is True


@pytest.mark.parametrize("entry", ["not a dict", 42, None, ["list"]])
def test_a_history_with_foreign_entries_is_treated_as_unusable(config, entry):
    guard = RestartGuard(config)
    guard._dir.mkdir(parents=True)
    (guard._dir / "restart-history.json").write_text(json.dumps([entry]))

    assert guard.record_and_allow_self_restart(1_800_000_000.0, "stuck") is False
    assert guard.record_unexpected_restart(1_800_000_000.0) == 1


def test_start_survives_a_history_with_foreign_entries(config, registry, clock):
    guard = RestartGuard(config)
    guard._dir.mkdir(parents=True)
    (guard._dir / "restart-history.json").write_text('["x"]')
    guard.write_marker(MARKER_RUNNING)
    watchdog = _watchdog(config, registry, clock)
    watchdog._alert_async = MagicMock()

    watchdog._on_process_start()

    watchdog._alert_async.assert_called_once()

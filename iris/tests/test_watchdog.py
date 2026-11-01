"""Watchdog: detect a deadlocked model pool, fail open runs, alert, restart at most every 30 min."""

# pylint: disable=protected-access
import threading
import time
from unittest.mock import MagicMock, patch

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris import watchdog as watchdog_module  # noqa: E402
from iris.llm.external.openai_chat import DirectOpenAIChatModel  # noqa: E402
from iris.watchdog import (  # noqa: E402
    EXIT_CODE,
    RESTART_MESSAGE,
    Watchdog,
    format_thread_dump,
    track_run,
    untrack_run,
)


def _watchdog(tmp_path, locks, **overrides):
    kwargs = {
        "locks_fn": lambda: locks,
        "alert_fn": MagicMock(),
        "exit_fn": MagicMock(),
        "sleep_fn": lambda _seconds: None,
        "last_restart_file": str(tmp_path / "last-restart"),
    }
    kwargs.update(overrides)
    return Watchdog(**kwargs)


def test_a_lock_held_on_two_checks_is_stuck(tmp_path):
    lock = threading.Lock()
    watchdog = _watchdog(tmp_path, {"luna-medium": lock, "sol": threading.Lock()})

    with lock:
        assert watchdog.check() == set()
        assert watchdog.check() == {"luna-medium"}


def test_a_lock_released_in_between_is_not_stuck(tmp_path):
    lock = threading.Lock()
    watchdog = _watchdog(tmp_path, {"luna-medium": lock})

    with lock:
        watchdog.check()
    assert watchdog.check() == set()


def test_the_real_openai_pool_lock_is_found():
    model = DirectOpenAIChatModel(
        id="luna-medium",
        type="openai_chat",
        model="gpt-test",
        api_key="sk-test",  # pragma: allowlist secret
        base_url="http://127.0.0.1:9/v1",
    )
    with patch(
        "iris.llm.llm_manager.LlmManager", return_value=MagicMock(entries=[model])
    ):
        locks = watchdog_module.model_pool_locks()

    pool = model.get_client()._client._transport._pool
    assert locks == {"luna-medium": pool._optional_thread_lock._lock}


def test_trip_fails_open_runs_alerts_quietly_and_exits(tmp_path):
    alert, exit_fn = MagicMock(), MagicMock()
    watchdog = _watchdog(tmp_path, {}, alert_fn=alert, exit_fn=exit_fn)
    callback = MagicMock()
    callback.fail.return_value = True
    track_run(callback)
    try:
        watchdog.trip({"luna-medium"})
    finally:
        untrack_run(callback)

    callback.fail.assert_called_once_with(RESTART_MESSAGE, code="restart")
    title, message, priority = alert.call_args.args
    assert "restarting" in title and priority == -1
    assert "luna-medium" in message and "Failed 1 open run(s)" in message
    exit_fn.assert_called_with(EXIT_CODE)


def test_a_second_trip_within_30_minutes_stays_up_and_pages(tmp_path):
    (tmp_path / "last-restart").write_text(str(time.time() - 600))
    alert, exit_fn = MagicMock(), MagicMock()
    watchdog = _watchdog(tmp_path, {}, alert_fn=alert, exit_fn=exit_fn)

    watchdog.trip({"luna-medium"})

    exit_fn.assert_not_called()
    assert alert.call_args.args[2] == 1


def test_a_stuck_run_does_not_hold_up_the_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog_module, "FAIL_RUNS_BUDGET_SECONDS", 0.2)
    exit_fn = MagicMock()
    watchdog = _watchdog(tmp_path, {}, exit_fn=exit_fn)
    callback = MagicMock()
    callback.fail.side_effect = lambda *_a, **_k: time.sleep(2)
    track_run(callback)
    try:
        started = time.monotonic()
        watchdog.trip({"luna-medium"})
    finally:
        untrack_run(callback)

    assert time.monotonic() - started < 1
    exit_fn.assert_called_with(EXIT_CODE)


def test_the_dump_folds_identical_stacks():
    release = threading.Event()
    threads = [threading.Thread(target=release.wait, daemon=True) for _ in range(30)]
    for thread in threads:
        thread.start()
    try:
        dump = format_thread_dump()
    finally:
        release.set()

    assert "--- 30 thread(s)" in dump

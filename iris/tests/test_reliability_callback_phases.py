"""Run phases of the status callbacks: one terminal frame per run, and the watchdog's sends."""

# pylint: disable=protected-access

import threading
from unittest.mock import MagicMock, patch

import requests

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.web.status import status_update  # noqa: E402
from iris.web.status.status_update import (  # noqa: E402
    WATCHDOG_POST_ATTEMPTS,
    WATCHDOG_POST_TIMEOUT_SECONDS,
    ChatRunCallback,
    RunPhase,
)


def _ok():
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    return response


def _callback():
    callback = ChatRunCallback(run_id="run-token", base_url="http://artemis")
    callback._post_status_payload = MagicMock(  # pylint: disable=protected-access
        return_value=_ok()
    )
    return callback


def _posted(callback):
    # pylint: disable=protected-access
    return [call.args[0] for call in callback._post_status_payload.call_args_list]


def test_watchdog_fail_sends_one_bounded_failed_frame():
    callback = _callback()

    assert callback.watchdog_fail("too slow", "timeout") is True

    assert callback.phase is RunPhase.TERMINAL
    assert callback.closed_by_watchdog is True
    payload = _posted(callback)[-1]
    assert payload["runState"] == "FAILED"
    assert payload["error"]["code"] == "timeout"
    # pylint: disable=protected-access
    assert callback._post_status_payload.call_args.kwargs == {
        "timeout": WATCHDOG_POST_TIMEOUT_SECONDS
    }


def test_watchdog_fail_retries_a_bounded_number_of_times():
    callback = _callback()
    failing = MagicMock()
    failing.raise_for_status.side_effect = requests.exceptions.HTTPError("502")
    callback._post_status_payload.return_value = (  # pylint: disable=protected-access
        failing
    )

    with patch("time.sleep"):
        assert callback.watchdog_fail("too slow", "timeout") is False

    assert len(_posted(callback)) == WATCHDOG_POST_ATTEMPTS


def test_pipeline_sends_after_a_watchdog_fail_are_dropped_without_sentry():
    callback = _callback()
    callback.watchdog_fail("too slow", "timeout")
    sent = len(_posted(callback))

    with patch.object(status_update, "capture_message") as capture:
        assert callback.send_result("late answer") is False
        assert callback.finish() is False

    assert len(_posted(callback)) == sent
    capture.assert_not_called()


def test_rejected_terminal_send_without_the_watchdog_still_reaches_sentry():
    callback = _callback()
    callback.finish()

    with patch.object(status_update, "capture_message") as capture:
        assert callback.finish() is False

    capture.assert_called_once()


def test_no_watchdog_fail_once_the_answer_is_on_its_way():
    callback = _callback()
    callback.send_result("the answer")

    assert callback.phase is RunPhase.ANSWER_SENDING
    assert callback.answer_sent_at is not None
    assert callback.watchdog_fail("too slow", "timeout") is False
    assert callback.phase is RunPhase.ANSWER_SENDING


def test_watchdog_finish_waits_for_the_answer_post():
    callback = _callback()
    release = threading.Event()
    in_post = threading.Event()

    def slow_post(payload, **_kwargs):
        if payload.get("result") == "the answer":
            in_post.set()
            release.wait(5)
        return _ok()

    callback._post_status_payload = MagicMock(  # pylint: disable=protected-access
        side_effect=slow_post
    )
    sender = threading.Thread(target=callback.send_result, args=("the answer",))
    sender.start()
    assert in_post.wait(5)

    assert callback.answer_post_in_flight is True
    assert callback.watchdog_finish() is False

    release.set()
    sender.join(5)
    assert callback.watchdog_finish() is True
    assert _posted(callback)[-1]["runState"] == "FINISHED"


def test_watchdog_finish_carries_an_undelivered_answer():
    callback = _callback()
    failing = MagicMock()
    failing.raise_for_status.side_effect = requests.exceptions.HTTPError("502")
    callback._post_status_payload.return_value = (  # pylint: disable=protected-access
        failing
    )
    with patch("time.sleep"):
        assert callback.send_result("the answer") is False

    callback._post_status_payload.return_value = (  # pylint: disable=protected-access
        _ok()
    )
    assert callback.watchdog_finish() is True

    payload = _posted(callback)[-1]
    assert payload["runState"] == "FINISHED"
    assert payload["result"] == "the answer"


def test_a_pipeline_finish_and_a_watchdog_fail_never_both_go_out():
    for _ in range(50):
        callback = _callback()
        start = threading.Barrier(2)

        def finish(cb=callback, barrier=start):
            barrier.wait()
            cb.finish()

        def fail(cb=callback, barrier=start):
            barrier.wait()
            cb.watchdog_fail("too slow", "timeout")

        threads = [threading.Thread(target=finish), threading.Thread(target=fail)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)

        terminal = [p for p in _posted(callback) if p["runState"] != "RUNNING"]
        assert len(terminal) == 1


def test_heartbeat_is_a_bare_running_frame():
    callback = _callback()
    callback.watchdog_heartbeat()
    callback._drain_running_updates()  # pylint: disable=protected-access

    assert _posted(callback)[-1] == {"runState": "RUNNING"}


def test_entering_answer_sending_marks_the_post_in_flight_in_one_step():
    callback = _callback()
    seen = {}

    def post(payload, **_kwargs):
        if payload.get("result") == "the answer":
            # The watchdog looking now must see the POST in flight and keep away.
            seen["finish_during_post"] = callback.watchdog_finish()
            seen["in_flight"] = callback.answer_post_in_flight
        return MagicMock(status_code=200, raise_for_status=MagicMock())

    callback._post_status_payload = MagicMock(  # pylint: disable=protected-access
        side_effect=post
    )
    assert callback._enter_answer_sending()  # pylint: disable=protected-access
    assert callback.answer_post_in_flight is True
    assert callback.watchdog_finish() is False
    callback._answer_post_in_flight = False  # pylint: disable=protected-access

    assert callback.send_result("the answer") is True
    assert seen == {"finish_during_post": False, "in_flight": True}
    assert callback.answer_post_in_flight is False


def test_watchdog_fail_bills_the_usage_the_run_accrued_once():
    from iris.common.token_usage_dto import (  # pylint: disable=import-outside-toplevel
        TokenUsageDTO,
    )

    callback = _callback()
    usage = []
    callback.attach_usage(usage)
    first, second = TokenUsageDTO(numInputTokens=10), TokenUsageDTO(numInputTokens=20)
    usage.append(first)
    callback.send_suggestions(["s"])  # a RUNNING frame without tokens
    usage.append(second)

    assert callback.watchdog_fail("too slow", "timeout") is True

    payload = _posted(callback)[-1]
    assert [t["numInputTokens"] for t in payload["tokens"]] == [10, 20]


def test_watchdog_finish_does_not_bill_usage_the_answer_already_carried():
    from iris.common.token_usage_dto import (  # pylint: disable=import-outside-toplevel
        TokenUsageDTO,
    )

    callback = _callback()
    usage = [TokenUsageDTO(numInputTokens=10)]
    callback.attach_usage(usage)
    callback.send_result("the answer", tokens=usage)
    usage.append(TokenUsageDTO(numInputTokens=5))  # e.g. the title call

    assert callback.watchdog_finish() is True

    payload = _posted(callback)[-1]
    assert [t["numInputTokens"] for t in payload["tokens"]] == [5]


def test_non_chat_watchdog_frames_carry_the_accrued_usage():
    from iris.common.token_usage_dto import (  # pylint: disable=import-outside-toplevel
        TokenUsageDTO,
    )
    from iris.web.status.status_update import (  # pylint: disable=import-outside-toplevel
        StruggleInterventionCallback,
    )

    callback = StruggleInterventionCallback(run_id="run-token", base_url="http://a")
    callback._post_status_payload = MagicMock(  # pylint: disable=protected-access
        return_value=_ok()
    )
    callback.attach_usage([TokenUsageDTO(numInputTokens=7)])

    assert callback.watchdog_fail("too slow", "timeout") is True

    payload = callback._post_status_payload.call_args.args[
        0
    ]  # pylint: disable=protected-access
    assert [t["numInputTokens"] for t in payload["tokens"]] == [7]


def test_a_retried_answer_blocks_the_watchdog_until_it_is_booked():
    from iris.common.token_usage_dto import (  # pylint: disable=import-outside-toplevel
        TokenUsageDTO,
    )

    callback = _callback()
    usage = [TokenUsageDTO(numInputTokens=10)]
    callback.attach_usage(usage)
    failing = MagicMock()
    failing.raise_for_status.side_effect = requests.exceptions.HTTPError("502")
    callback._post_status_payload.return_value = failing
    with patch("time.sleep"):
        assert callback.send_result("the answer", tokens=usage) is False

    seen = {}

    def retry_post(payload, **_kwargs):
        if payload.get("result") == "the answer" and payload["runState"] == "RUNNING":
            # Artemis has the retry but the response is not back yet.
            seen["finish_during_retry"] = callback.watchdog_finish()
        return _ok()

    callback._post_status_payload = MagicMock(side_effect=retry_post)
    assert callback.send_suggestions(["s"]) is True
    assert seen == {"finish_during_retry": False}

    assert callback.watchdog_finish() is True
    payload = _posted(callback)[-1]
    assert payload["runState"] == "FINISHED"
    assert payload["tokens"] == []  # the retry already billed them
    assert "result" not in payload or payload["result"] in (None, "")


def test_the_watchdogs_own_terminal_post_counts_as_in_flight():
    callback = _callback()
    seen = {}

    def post(*_args, **_kwargs):
        seen["in_flight"] = callback.terminal_post_in_flight
        return _ok()

    callback._post_status_payload = MagicMock(side_effect=post)
    assert callback.watchdog_fail("too slow", "timeout") is True

    assert seen == {"in_flight": True}
    assert callback.terminal_post_in_flight is False


def test_a_failing_payload_build_does_not_leave_the_terminal_flag_set():
    callback = _callback()
    callback._watchdog_payload = MagicMock(side_effect=ValueError("bad status"))

    try:
        callback.watchdog_fail("too slow", "timeout")
    except ValueError:
        pass

    assert callback.terminal_post_in_flight is False

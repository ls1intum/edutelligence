from unittest.mock import patch

import requests

from iris.domain.data.verdict_dto import VerdictDTO
from iris.web.status.status_update import AskUserStatusCallback


class _Response:
    status_code = 200

    def raise_for_status(self):
        return None


def _ok():
    return _Response()


def _callback(event=None) -> AskUserStatusCallback:
    return AskUserStatusCallback(
        run_id="run-1", base_url="https://artemis.example", event=event
    )


def test_init_builds_ask_user_url_and_initial_running_status():
    cb = _callback(event="USER_STARTS_QUIZ")

    assert (
        cb.url
        == "https://artemis.example/api/iris/internal/pipelines/ask-user/runs/run-1/status"
    )
    assert cb.status.run_state == "RUNNING"
    assert cb.status.event == "USER_STARTS_QUIZ"


def test_update_sends_running_update():
    cb = _callback()
    with patch("requests.post", return_value=_ok()) as post:
        assert cb.update() is True

    payload = post.call_args.kwargs["json"]
    assert payload["runState"] == "RUNNING"


def test_update_sends_result_as_running_state():
    # Ask-user's answer-bearing update is a mid-conversation message, not the
    # end of the run, so it must stay RUNNING rather than a terminal state.
    cb = _callback()
    with patch("requests.post", return_value=_ok()) as post:
        assert cb.update(result="Here is your question.") is True

    payload = post.call_args.kwargs["json"]
    assert payload["runState"] == "RUNNING"
    assert payload["result"] == "Here is your question."
    assert payload["error"] is None


def test_update_forwards_verdict_and_tokens_fields():
    cb = _callback()
    verdict = VerdictDTO(verdict="SUSPICIOUS", reasoning="Wrong answer.")
    with patch("requests.post", return_value=_ok()) as post:
        cb.update(result="Quiz finished.", tokens=[], verdict=verdict)

    payload = post.call_args.kwargs["json"]
    assert payload["verdict"] == {"verdict": "SUSPICIOUS", "reasoning": "Wrong answer."}
    assert payload["tokens"] == []


def test_update_clears_result_field_after_successful_delivery():
    # Once the answer-bearing update() is delivered successfully, "result" must
    # be cleared like any other transient field so it is not re-sent by a later
    # heartbeat.
    cb = _callback()
    with patch("requests.post", return_value=_ok()):
        cb.update(result="Here is your question.")

    with patch("requests.post", return_value=_ok()) as post:
        assert cb.update() is True

    payload = post.call_args.kwargs["json"]
    assert payload["result"] is None


def test_finish_does_not_resend_result_after_successful_update():
    # Regression test: a successfully delivered answer must not be sent again
    # by the pipeline's terminal finish() call.
    cb = _callback()
    with patch("requests.post", return_value=_ok()):
        cb.update(result="Here is your question.")

    with patch("requests.post", return_value=_ok()) as post:
        assert cb.finish() is True

    payload = post.call_args.kwargs["json"]
    assert payload["result"] is None
    assert payload["runState"] == "FINISHED"


class _FailedResponse:
    status_code = 500

    def raise_for_status(self):
        raise requests.exceptions.RequestException("boom")


def test_finish_still_carries_result_if_prior_update_failed():
    # If the answer-bearing update() failed to send, "result" must be preserved
    # on the reusable status DTO so the terminal finish() gets one more chance
    # to deliver it, instead of silently dropping the answer.
    cb = _callback()
    with patch("requests.post", return_value=_FailedResponse()):
        assert cb.update(result="Here is your question.") is False

    with patch("requests.post", return_value=_ok()) as post:
        assert cb.finish() is True

    payload = post.call_args.kwargs["json"]
    assert payload["result"] == "Here is your question."
    assert payload["runState"] == "FINISHED"


def test_fail_sends_failed_state():
    cb = _callback()
    with patch("requests.post", return_value=_ok()) as post:
        assert cb.fail("Something went wrong") is True

    payload = post.call_args.kwargs["json"]
    assert payload["runState"] == "FAILED"
    assert payload["error"]["message"] == "Something went wrong"


def test_fail_marks_run_terminal_so_later_updates_are_rejected():
    cb = _callback()
    with patch("requests.post", return_value=_ok()):
        cb.fail("Fatal error.")

    with patch("requests.post") as post:
        assert cb.update(result="too late") is False
    post.assert_not_called()

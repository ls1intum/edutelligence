from unittest.mock import patch

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


def test_in_progress_ignores_message_and_sends_running_update():
    cb = _callback()
    with patch("requests.post", return_value=_ok()) as post:
        assert cb.in_progress("Thinking ...") is True

    payload = post.call_args.kwargs["json"]
    assert payload["runState"] == "RUNNING"


def test_done_sends_running_state_not_finished():
    # Ask-user "done" is a mid-conversation answer, not the end of the run,
    # so it must stay RUNNING rather than transitioning to a terminal state.
    cb = _callback()
    with patch("requests.post", return_value=_ok()) as post:
        assert cb.done("ignored message", final_result="Here is your question.") is True

    payload = post.call_args.kwargs["json"]
    assert payload["runState"] == "RUNNING"
    assert payload["result"] == "Here is your question."
    assert payload["error"] is None


def test_done_forwards_verdict_and_tokens_fields():
    cb = _callback()
    verdict = VerdictDTO(verdict="SUSPICIOUS", reasoning="Wrong answer.")
    with patch("requests.post", return_value=_ok()) as post:
        cb.done(final_result="Quiz finished.", tokens=[], verdict=verdict)

    payload = post.call_args.kwargs["json"]
    assert payload["verdict"] == {"verdict": "SUSPICIOUS", "reasoning": "Wrong answer."}
    assert payload["tokens"] == []


def test_done_does_not_mark_run_as_terminal():
    cb = _callback()
    with patch("requests.post", return_value=_ok()):
        cb.done(final_result="Here is your question.")

    # A later update must still be accepted, proving the base class did not
    # treat this "done" call as the terminal send.
    with patch("requests.post", return_value=_ok()) as post:
        assert cb.update(result="Another update") is True
    assert post.called


def test_error_delegates_to_fail_and_sends_failed_state():
    cb = _callback()
    with patch("requests.post", return_value=_ok()) as post:
        assert cb.error("Something went wrong") is True

    payload = post.call_args.kwargs["json"]
    assert payload["runState"] == "FAILED"
    assert payload["error"]["message"] == "Something went wrong"


def test_error_marks_run_terminal_so_later_updates_are_rejected():
    cb = _callback()
    with patch("requests.post", return_value=_ok()):
        cb.error("Fatal error.")

    with patch("requests.post") as post:
        assert cb.update(result="too late") is False
    post.assert_not_called()

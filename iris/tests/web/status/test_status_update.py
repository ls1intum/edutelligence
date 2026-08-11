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


def test_update_does_not_clear_result_field_afterwards():
    # Unlike the base StatusCallback, ask-user's "result" must survive to the
    # pipeline's terminal finish(), so it must not be cleared as a transient
    # field after a successful update() the way it is for other pipelines.
    cb = _callback()
    with patch("requests.post", return_value=_ok()):
        cb.update(result="Here is your question.")

    with patch("requests.post", return_value=_ok()) as post:
        assert cb.update() is True

    payload = post.call_args.kwargs["json"]
    assert payload["result"] == "Here is your question."


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

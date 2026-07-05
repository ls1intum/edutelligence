from unittest.mock import patch

import requests

from iris.domain.status.chat_status_update_dto import ChatStatusUpdateDTO
from iris.domain.status.run_state_dto import RunStateEnum
from iris.web.status.status_update import StatusCallback


class _Response:
    status_code = 200

    def raise_for_status(self):
        return None


def _callback() -> StatusCallback:
    return StatusCallback(
        url="https://artemis.example/status",
        run_id="run-1",
        status=ChatStatusUpdateDTO(run_state=RunStateEnum.RUNNING),
    )


def test_update_posts_running_and_fields():
    cb = _callback()
    with patch("requests.post", return_value=_Response()) as post:
        assert cb.update(result="answer") is True

    payload = post.call_args.kwargs["json"]
    assert payload["runState"] == "RUNNING"
    assert payload["result"] == "answer"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer run-1"


def test_finish_is_terminal_and_last():
    cb = _callback()
    with patch("requests.post", return_value=_Response()) as post:
        assert cb.finish(result="answer") is True
        assert cb.update(result="late") is False

    assert post.call_count == 1
    assert post.call_args.kwargs["json"]["runState"] == "FINISHED"


def test_fail_builds_error_object():
    cb = _callback()
    with patch("requests.post", return_value=_Response()) as post:
        assert cb.fail(message="m", code="C") is True

    payload = post.call_args.kwargs["json"]
    assert payload["runState"] == "FAILED"
    assert payload["error"] == {"message": "m", "code": "C"}


def test_terminal_drains_async_queue_first():
    cb = _callback()
    with patch("requests.post", return_value=_Response()) as post:
        cb.status.result = "async"
        cb._enqueue_in_progress_update()  # pylint: disable=protected-access
        assert cb.finish(result="terminal") is True

    payloads = [call.kwargs["json"] for call in post.call_args_list]
    assert [payload["result"] for payload in payloads] == ["async", "terminal"]
    assert [payload["runState"] for payload in payloads] == ["RUNNING", "FINISHED"]


def test_non_terminal_request_exception_returns_false():
    cb = _callback()
    with patch("requests.post", side_effect=requests.RequestException):
        assert cb.update(result="answer") is False

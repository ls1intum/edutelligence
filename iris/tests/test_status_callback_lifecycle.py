from concurrent.futures import Future
from unittest.mock import patch

import requests

from iris.common.token_usage_dto import TokenUsageDTO
from iris.domain.ingestion.ingestion_status_update_dto import (
    IngestionStatusUpdateDTO,
)
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


def _ingestion_callback() -> StatusCallback:
    """A callback backed by the reusable ingestion status DTO, which carries
    the transient transcription ``result`` checkpoint across updates."""
    return StatusCallback(
        url="https://artemis.example/status",
        run_id="run-1",
        status=IngestionStatusUpdateDTO(run_state=RunStateEnum.RUNNING, id=7),
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
        cb._enqueue_running_update()  # pylint: disable=protected-access
        assert cb.finish(result="terminal") is True

    payloads = [call.kwargs["json"] for call in post.call_args_list]
    assert [payload["result"] for payload in payloads] == ["async", "terminal"]
    assert [payload["runState"] for payload in payloads] == ["RUNNING", "FINISHED"]


def test_non_terminal_request_exception_returns_false():
    cb = _callback()
    with patch("requests.post", side_effect=requests.RequestException):
        assert cb.update(result="answer") is False


def test_successful_update_clears_transient_result_and_page_numbers():
    """After a delivered checkpoint update, transient result-like fields are
    cleared on the reusable DTO so later heartbeats don't re-send them."""
    cb = _ingestion_callback()
    with patch("requests.post", return_value=_Response()):
        assert cb.update(result="checkpoint-1", display_page_numbers=[1, 2]) is True

    assert cb.status.result is None
    assert cb.status.display_page_numbers is None


def test_successful_update_keeps_persistent_fields():
    """Persistent fields (accumulated tokens, identity id) must survive a
    successful update and NOT be cleared as transient."""
    cb = _ingestion_callback()
    token = TokenUsageDTO(num_input_tokens=5)
    with patch("requests.post", return_value=_Response()):
        assert cb.update(result="checkpoint-1", tokens=[token]) is True

    assert cb.status.tokens == [token]
    assert cb.status.id == 7


def test_next_heartbeat_does_not_resend_cleared_result():
    """A bare heartbeat following a delivered checkpoint must not re-send the
    stale checkpoint JSON."""
    cb = _ingestion_callback()
    with patch("requests.post", return_value=_Response()) as post:
        assert cb.update(result="checkpoint-1") is True
        assert cb.update() is True

    bodies = [call.kwargs["json"] for call in post.call_args_list]
    assert bodies[0]["result"] == "checkpoint-1"
    assert bodies[1]["result"] is None
    assert bodies[1]["id"] == 7


def test_failed_update_keeps_transient_result_for_retry():
    """If the POST fails, the transient result is kept so the next update
    re-attempts delivery instead of silently dropping the checkpoint."""
    cb = _ingestion_callback()
    with patch("requests.post", side_effect=requests.RequestException):
        assert cb.update(result="checkpoint-1") is False

    assert cb.status.result == "checkpoint-1"

    with patch("requests.post", return_value=_Response()) as post:
        assert cb.update() is True

    assert post.call_args.kwargs["json"]["result"] == "checkpoint-1"


def test_running_update_executor_creation_uses_lock():
    cb = _callback()
    entered = False

    class ProbeLock:
        def __enter__(self):
            nonlocal entered
            entered = True

        def __exit__(self, *_args):
            return None

    cb._running_update_lock = ProbeLock()  # pylint: disable=protected-access
    with patch("requests.post", return_value=_Response()):
        cb._get_running_update_executor()  # pylint: disable=protected-access
        cb._shutdown_running_update_executor()  # pylint: disable=protected-access

    assert entered is True


def test_terminal_send_shuts_down_running_update_executor():
    cb = _callback()
    shutdown_calls = []

    class ImmediateExecutor:
        def submit(self, fn, *args, **kwargs):
            future = Future()
            future.set_result(fn(*args, **kwargs))
            return future

        def shutdown(self, wait=False):
            shutdown_calls.append(wait)

    with (
        patch(
            "iris.web.status.status_update.TracedThreadPoolExecutor",
            return_value=ImmediateExecutor(),
        ),
        patch("requests.post", return_value=_Response()),
    ):
        cb._enqueue_running_update()  # pylint: disable=protected-access
        assert cb.finish(result="terminal") is True

    assert shutdown_calls == [False]

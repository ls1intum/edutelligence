from unittest.mock import patch

import requests

from iris.domain.status.activity_dto import ActivityDTO, ActivityKind, ActivityState
from iris.web.status.status_update import ChatRunCallback


class _Response:
    status_code = 200

    def raise_for_status(self):
        return None


def _ok():
    return _Response()


def _callback() -> ChatRunCallback:
    return ChatRunCallback("run-1", "https://artemis.example", None)


def _activity(state=ActivityState.RUNNING):
    return ActivityDTO(
        id="act-1",
        kind=ActivityKind.TOOL,
        name="lecture_content_retrieval",
        state=state,
    )


def test_send_result_retries_then_succeeds():
    cb = _callback()
    with (
        patch("requests.post") as post,
        patch("time.sleep") as sleep,
    ):
        post.side_effect = [
            requests.RequestException(),
            requests.RequestException(),
            _ok(),
        ]
        assert cb.send_result("answer", tokens=[]) is True

    assert post.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [1, 2]
    assert post.call_args.kwargs["json"]["result"] == "answer"


def test_undelivered_result_rides_next_send():
    cb = _callback()
    with (
        patch("requests.post") as post,
        patch("time.sleep"),
    ):
        post.side_effect = [
            requests.RequestException(),
            requests.RequestException(),
            requests.RequestException(),
            _ok(),
            _ok(),
        ]
        assert cb.send_result("answer", tokens=[]) is False
        assert cb.send_suggestions(["s1"]) is True
        suggestions_body = post.call_args.kwargs["json"]
        assert suggestions_body["result"] == "answer"
        assert suggestions_body["suggestions"] == ["s1"]

        assert cb.finish() is True
        finish_body = post.call_args.kwargs["json"]
        assert finish_body["result"] is None


def test_activity_snapshot_is_async_and_seq_ordered():
    cb = _callback()
    with patch("requests.post", return_value=_ok()) as post:
        cb.activity_snapshot([_activity()], 1)
        cb.activity_snapshot([_activity(ActivityState.FINISHED)], 2)
        cb._drain_in_progress_updates()  # pylint: disable=protected-access

    payloads = [call.kwargs["json"] for call in post.call_args_list]
    assert [payload["activitySeq"] for payload in payloads] == [1, 2]
    assert [payload["runState"] for payload in payloads] == ["RUNNING", "RUNNING"]


def test_send_result_carries_authoritative_activities():
    cb = _callback()
    with patch("requests.post", return_value=_ok()) as post:
        assert cb.send_result(
            "answer",
            tokens=[],
            activities=[_activity(ActivityState.FINISHED)],
            activity_seq=7,
        )

    payload = post.call_args.kwargs["json"]
    assert payload["activities"][0]["state"] == "FINISHED"
    assert payload["activitySeq"] == 7

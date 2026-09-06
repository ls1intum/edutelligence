from unittest.mock import patch

import pytest
import requests

from iris.common.token_usage_dto import TokenUsageDTO
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


def test_terminal_finish_retries_carried_result_on_transient_failure():
    """If send_result exhausted its retries, the terminal finish is the last
    chance to deliver the carried answer, so it must retry with the same
    backoff instead of dropping it on a single transient failure."""
    cb = _callback()
    with (
        patch("requests.post") as post,
        patch("time.sleep") as sleep,
    ):
        post.side_effect = [
            # send_result: three failures -> answer carried forward.
            requests.RequestException(),
            requests.RequestException(),
            requests.RequestException(),
            # finish (carrying the answer): fail, fail, then succeed.
            requests.RequestException(),
            requests.RequestException(),
            _ok(),
        ]
        assert cb.send_result("answer", tokens=[]) is False
        assert cb.finish() is True

    assert post.call_count == 6
    # Same backoff schedule (1s, 2s) for both the send_result and the finish
    # retry runs.
    assert [call.args[0] for call in sleep.call_args_list] == [1, 2, 1, 2]
    finish_body = post.call_args.kwargs["json"]
    assert finish_body["runState"] == "FINISHED"
    assert finish_body["result"] == "answer"
    assert finish_body["final"] is True
    # A successful terminal delivery clears the carried answer.
    assert cb._undelivered_result_fields is None  # pylint: disable=protected-access


def test_terminal_finish_without_carried_result_is_single_shot():
    """Terminal sends that carry no undelivered answer must stay single-shot
    so the common (already-delivered) path is not slowed by retries."""
    cb = _callback()
    with (
        patch("requests.post") as post,
        patch("time.sleep") as sleep,
    ):
        post.side_effect = [requests.RequestException()]
        assert cb.finish() is False

    assert post.call_count == 1
    sleep.assert_not_called()


def test_send_intermediate_uses_final_false_without_retry_or_carry_forward():
    cb = _callback()
    with (
        patch("requests.post") as post,
        patch("time.sleep") as sleep,
    ):
        post.side_effect = [requests.RequestException(), _ok()]

        assert cb.send_intermediate("Let me check first.") is False
        assert post.call_count == 1

        assert cb.send_suggestions(["s1"]) is True
        suggestions_body = post.call_args.kwargs["json"]

    sleep.assert_not_called()
    assert suggestions_body["runState"] == "RUNNING"
    assert suggestions_body["result"] is None
    assert suggestions_body["final"] is None


def test_send_result_uses_final_true():
    cb = _callback()
    with patch("requests.post", return_value=_ok()) as post:
        assert cb.send_result("answer", tokens=[]) is True

    payload = post.call_args.kwargs["json"]
    assert payload["result"] == "answer"
    assert payload["final"] is True


def test_activity_snapshot_is_async_and_seq_ordered():
    cb = _callback()
    with patch("requests.post", return_value=_ok()) as post:
        cb.activity_snapshot([_activity()], 1)
        cb.activity_snapshot([_activity(ActivityState.FINISHED)], 2)
        cb._drain_running_updates()  # pylint: disable=protected-access

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


def _token(name: str) -> TokenUsageDTO:
    return TokenUsageDTO(model=name, numInputTokens=10, numOutputTokens=5)


def _sent_tokens(post) -> list[list[str]]:
    """The `model` of every token in every payload that was actually posted."""
    return [
        [token["model"] for token in call.kwargs["json"]["tokens"]]
        for call in post.call_args_list
    ]


def test_usage_already_reported_is_not_sent_again():
    """
    Artemis appends the tokens of every callback to the run's trace without deduplicating
    them, so re-sending the answer's usage on the trailing finish bills it twice. Each send
    carries only what the previous ones did not deliver.
    """
    cb = _callback()
    answer, title = _token("answer"), _token("title")
    with patch("requests.post") as post:
        post.return_value = _ok()
        assert cb.send_result("answer", tokens=[answer]) is True
        assert cb.finish(tokens=[answer, title]) is True

    assert _sent_tokens(post) == [["answer"], ["title"]]


def test_suggestions_between_result_and_finish_do_not_disturb_the_split():
    cb = _callback()
    answer, title = _token("answer"), _token("title")
    with patch("requests.post") as post:
        post.return_value = _ok()
        cb.send_result("answer", tokens=[answer])
        cb.send_suggestions(["s1"], session_title="t")
        cb.finish(tokens=[answer, title])

    assert _sent_tokens(post) == [["answer"], [], ["title"]]


def test_usage_of_an_undelivered_result_rides_the_next_send():
    """The counter advances on delivery, not on the attempt, so nothing is lost."""
    cb = _callback()
    answer, title = _token("answer"), _token("title")
    with (
        patch("requests.post") as post,
        patch("time.sleep"),
    ):
        post.side_effect = [
            requests.RequestException(),
            requests.RequestException(),
            requests.RequestException(),
            _ok(),
        ]
        assert cb.send_result("answer", tokens=[answer]) is False
        assert cb.finish(tokens=[answer, title]) is True

    assert _sent_tokens(post)[-1] == ["answer", "title"]


def test_suggestions_that_carry_an_undelivered_answer_also_carry_its_usage():
    """
    A failed send_result rides along with the next send. That send delivers the answer, so
    it owes the answer's usage too, and the finish behind it owes only what came later.
    """
    cb = _callback()
    answer, title = _token("answer"), _token("title")
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
        assert cb.send_result("answer", tokens=[answer]) is False
        assert cb.send_suggestions(["s1"], session_title="t") is True
        assert cb.finish(tokens=[answer, title]) is True

    assert _sent_tokens(post)[-2:] == [["answer"], ["title"]]


def test_a_failed_answer_followed_by_a_failing_run_reports_everything_once():
    cb = _callback()
    answer, title = _token("answer"), _token("title")
    with (
        patch("requests.post") as post,
        patch("time.sleep"),
    ):
        post.side_effect = [
            requests.RequestException(),
            requests.RequestException(),
            requests.RequestException(),
            _ok(),
        ]
        assert cb.send_result("answer", tokens=[answer]) is False
        assert (
            cb.fail(
                "Generating interaction suggestions failed.", tokens=[answer, title]
            )
            is True
        )

    assert _sent_tokens(post)[-1] == ["answer", "title"]


def test_a_failure_after_a_delivered_answer_reports_only_the_rest():
    cb = _callback()
    answer, title = _token("answer"), _token("title")
    with patch("requests.post") as post:
        post.return_value = _ok()
        cb.send_result("answer", tokens=[answer])
        cb.fail("Error in processing response", tokens=[answer, title])

    assert _sent_tokens(post) == [["answer"], ["title"]]


def test_a_failure_before_any_answer_reports_everything():
    cb = _callback()
    answer, title = _token("answer"), _token("title")
    with patch("requests.post") as post:
        post.return_value = _ok()
        cb.fail(
            "An error occurred while running the chat pipeline.", tokens=[answer, title]
        )

    assert _sent_tokens(post) == [["answer", "title"]]


def test_activity_snapshots_do_not_move_the_token_cursor():
    cb = _callback()
    answer = _token("answer")
    with patch("requests.post") as post:
        post.return_value = _ok()
        cb.activity_snapshot([_activity()], 1)
        cb.send_result("answer", tokens=[answer])

    assert _sent_tokens(post)[-1] == ["answer"]


def test_retried_attempts_of_one_send_count_as_one_delivery():
    cb = _callback()
    answer, title = _token("answer"), _token("title")
    with (
        patch("requests.post") as post,
        patch("time.sleep"),
    ):
        post.side_effect = [requests.RequestException(), _ok(), _ok()]
        assert cb.send_result("answer", tokens=[answer]) is True
        assert cb.finish(tokens=[answer, title]) is True

    # Two attempts carried the answer, one delivered it; the finish still owes only the title.
    assert _sent_tokens(post) == [["answer"], ["answer"], ["title"]]


def test_a_partial_token_list_is_refused_rather_than_reported_twice():
    """
    Callers owe this callback the run's cumulative usage. A shorter list means someone
    passed a slice, and sending it would re-report what Artemis already has.
    """
    cb = _callback()
    answer, title = _token("answer"), _token("title")
    with patch("requests.post") as post:
        post.return_value = _ok()
        with patch("iris.web.status.status_update.capture_message") as captured:
            cb.send_result("answer", tokens=[answer, title])
            cb.finish(tokens=[title])

    assert _sent_tokens(post) == [["answer", "title"], []]
    assert "shrank from 2 to 1" in captured.call_args.args[0]


def test_update_refuses_to_carry_tokens():
    cb = _callback()
    with patch("requests.post") as post:
        post.return_value = _ok()
        with pytest.raises(ValueError, match="must not carry tokens"):
            cb.update(tokens=[_token("answer")])
    post.assert_not_called()

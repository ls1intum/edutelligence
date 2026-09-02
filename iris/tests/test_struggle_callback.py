from unittest.mock import patch

from iris.web.status.status_update import StruggleInterventionCallback


def test_callback_builds_struggle_url_and_status():
    cb = StruggleInterventionCallback(run_id="job-9", base_url="http://localhost:8080")
    assert cb.url == (
        "http://localhost:8080/api/iris/internal/pipelines/"
        "struggle-intervention/runs/job-9/status"
    )
    # the status object accepts the action result fields
    cb.status.action = "active"
    assert cb.status.action == "active"


class _Response:
    status_code = 200

    def raise_for_status(self):
        return None


def _delivered_callback() -> StruggleInterventionCallback:
    """A callback that has already sent its terminal frame, as post_agent_hook leaves it."""
    cb = StruggleInterventionCallback(run_id="job-9", base_url="http://localhost:8080")
    with patch("requests.post", return_value=_Response()):
        assert cb.finish() is True
    return cb


def test_the_trailing_finish_of_the_base_pipeline_is_not_an_anomaly():
    """
    post_agent_hook owns the terminal frame, and AbstractAgentPipeline closes every run with a
    finish of its own afterwards. That one is structural, so it must not raise a Sentry message
    on every single run.
    """
    cb = _delivered_callback()
    with (
        patch("requests.post") as post,
        patch("iris.web.status.status_update.capture_message") as captured,
    ):
        assert cb.finish() is False

    post.assert_not_called()
    captured.assert_not_called()


def test_a_second_trailing_finish_is_still_reported():
    """Only the one the pipeline's shape produces is absorbed; another is a real anomaly."""
    cb = _delivered_callback()
    with (
        patch("requests.post"),
        patch("iris.web.status.status_update.capture_message") as captured,
    ):
        cb.finish()
        cb.finish()

    assert captured.call_count == 1


def test_the_trailing_finish_after_a_failed_help_request_is_absorbed_too():
    """The help_request path fails the run instead of finishing it, and the base still finishes."""
    cb = StruggleInterventionCallback(run_id="job-9", base_url="http://localhost:8080")
    with patch("requests.post", return_value=_Response()):
        assert (
            cb.fail("help request produced silent, which this intent forbids") is True
        )

    with (
        patch("requests.post") as post,
        patch("iris.web.status.status_update.capture_message") as captured,
    ):
        assert cb.finish() is False

    post.assert_not_called()
    captured.assert_not_called()


def test_a_rejected_fail_is_still_reported():
    """A terminal frame that loses a failure is worth knowing about, absorbing it is not."""
    cb = _delivered_callback()
    with (
        patch("requests.post"),
        patch("iris.web.status.status_update.capture_message") as captured,
    ):
        assert cb.fail("something broke afterwards") is False

    captured.assert_called_once()

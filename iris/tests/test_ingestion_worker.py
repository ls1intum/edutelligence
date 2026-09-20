"""Unit tests for the pull-based ingestion worker with upstream discovery.

The worker's claim and heartbeat loops talk to discovered Artemis upstreams
over HTTP; here the transport is replaced with mocks so the tests cover the
worker's own logic: discovery and expiry, capacity accounting across
upstreams, auth pairing from the announcement, and heartbeat bookkeeping.
"""

# Tests reach into worker internals and import a couple of modules lazily; both are expected here.
# pylint: disable=protected-access,import-outside-toplevel

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from iris.common.boot_id import BOOT_ID
from iris.ingestion.worker import IngestionWorker


def _response(status_code=200, body=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = body or {}
    response.raise_for_status.return_value = None
    return response


def _thread(alive: bool):
    thread = MagicMock(spec=threading.Thread)
    thread.is_alive.return_value = alive
    return thread


def _run(worker, token, upstream_url, alive=True):
    run = MagicMock()
    run.thread = _thread(alive)
    run.upstream_url = upstream_url
    worker._active[token] = run  # pylint: disable=protected-access


class TestDiscovery:
    """Upstream discovery: announcement registration, refresh, and expiry."""

    def test_announcement_registers_an_upstream_with_its_token(self):
        worker = IngestionWorker()
        worker.register_upstream("http://a:8080/", "key-a")
        upstreams = worker._fresh_upstreams()  # pylint: disable=protected-access
        assert [u.url for u in upstreams] == ["http://a:8080"]
        assert upstreams[0].auth_token == "key-a"

    def test_reannouncement_refreshes_instead_of_duplicating(self):
        worker = IngestionWorker()
        worker.register_upstream("http://a:8080", "key-old")
        worker.register_upstream("http://a:8080/", "key-new")
        upstreams = worker._fresh_upstreams()  # pylint: disable=protected-access
        assert len(upstreams) == 1
        assert upstreams[0].auth_token == "key-new"

    def test_silent_upstream_expires_unless_it_still_owns_runs(self):
        worker = IngestionWorker()
        worker.register_upstream("http://a:8080", "key-a")
        worker.register_upstream("http://b:8080", "key-b")
        _run(worker, "token-b", "http://b:8080")
        stale = time.monotonic() - 100_000
        for upstream in worker._upstreams.values():  # pylint: disable=protected-access
            upstream.last_announced_monotonic = stale
        fresh = worker._fresh_upstreams()  # pylint: disable=protected-access
        # Neither is claimed from, but only the one without runs is dropped.
        assert fresh == []
        assert list(worker._upstreams) == [
            "http://b:8080"
        ]  # pylint: disable=protected-access


class TestUpstreamValidation:
    """register_upstream rejects a URL an allowlist or a plain scheme check would refuse,
    and the outbound requests never follow a redirect away from a validated upstream."""

    def test_rejects_a_url_with_no_http_scheme(self):
        worker = IngestionWorker()
        worker.register_upstream("ftp://a:8080", "key-a")
        assert worker._fresh_upstreams() == []  # pylint: disable=protected-access

    def test_accepts_any_http_url_when_no_allowlist_is_configured(self):
        worker = IngestionWorker()
        worker.register_upstream("http://a:8080", "key-a")
        assert len(worker._fresh_upstreams()) == 1  # pylint: disable=protected-access

    def test_allowlist_rejects_a_host_not_on_it(self):
        worker = IngestionWorker()
        # patch.object restores the shared settings singleton afterward: worker._config IS
        # settings.ingestion_worker, not a per-instance copy, so a plain assignment here would
        # leak the allowlist into every worker built by every later test in this process.
        with patch.object(
            worker._config, "allowed_upstream_hosts", ["a"]
        ):  # pylint: disable=protected-access
            worker.register_upstream("http://evil:8080", "key-evil")
        assert worker._fresh_upstreams() == []  # pylint: disable=protected-access

    def test_allowlist_accepts_a_listed_host_regardless_of_port(self):
        worker = IngestionWorker()
        with patch.object(
            worker._config, "allowed_upstream_hosts", ["a"]
        ):  # pylint: disable=protected-access
            worker.register_upstream("http://a:9999", "key-a")
        assert len(worker._fresh_upstreams()) == 1  # pylint: disable=protected-access

    def test_outbound_claim_never_follows_a_redirect(self):
        worker = IngestionWorker()
        worker.register_upstream("http://a:8080", "key-a")
        with patch.object(worker, "_start_job"):
            with patch(
                "iris.ingestion.worker.http_requests.post",
                return_value=_response(body={"jobs": []}),
            ) as post:
                worker._claim_once()  # pylint: disable=protected-access
        assert post.call_args.kwargs["allow_redirects"] is False


class TestClaim:
    """Claiming: capacity accounting, per-upstream token, and slot flow."""

    def test_claim_posts_free_capacity_with_the_announced_token(self):
        worker = IngestionWorker()
        worker.register_upstream("http://a:8080", "key-a")
        started = []
        with patch.object(
            worker, "_start_job", side_effect=lambda job, upstream: started.append(job)
        ):
            with patch(
                "iris.ingestion.worker.http_requests.post",
                return_value=_response(body={"jobs": [{"a": 1}, {"b": 2}]}),
            ) as post:
                worker._claim_once()  # pylint: disable=protected-access
        assert post.call_args.kwargs["json"] == {
            "bootId": BOOT_ID,
            "maxJobs": worker._config.capacity,  # pylint: disable=protected-access
        }
        assert post.call_args.kwargs["headers"] == {"Authorization": "key-a"}
        assert started == [{"a": 1}, {"b": 2}]

    def test_claim_clamps_an_over_generous_response_to_the_requested_slots(self):
        # The worker asked for at most `capacity` jobs; an upstream that ignores that (a bug, or a
        # misconfigured/non-Artemis issuer) and hands back more must not push this worker over its
        # own configured capacity.
        worker = IngestionWorker()
        worker.register_upstream("http://a:8080", "key-a")
        started = []
        with patch.object(
            worker,
            "_start_job",
            side_effect=lambda job, upstream: started.append(job) or True,
        ):
            with patch(
                "iris.ingestion.worker.http_requests.post",
                return_value=_response(
                    body={
                        "jobs": [
                            {"job": i}
                            for i in range(
                                worker._config.capacity + 3
                            )  # pylint: disable=protected-access
                        ]
                    }
                ),
            ):
                worker._claim_once()  # pylint: disable=protected-access
        assert (
            len(started) == worker._config.capacity
        )  # pylint: disable=protected-access

    def test_claim_does_nothing_before_any_upstream_announced(self):
        worker = IngestionWorker()
        with patch("iris.ingestion.worker.http_requests.post") as post:
            worker._claim_once()  # pylint: disable=protected-access
        post.assert_not_called()

    def test_claim_skips_the_request_when_no_slots_are_free(self):
        worker = IngestionWorker()
        worker.register_upstream("http://a:8080", "key-a")
        for i in range(worker._config.capacity):  # pylint: disable=protected-access
            _run(worker, f"token-{i}", "http://a:8080")
        with patch("iris.ingestion.worker.http_requests.post") as post:
            worker._claim_once()  # pylint: disable=protected-access
        post.assert_not_called()

    def test_remaining_slots_flow_to_the_next_upstream(self):
        worker = IngestionWorker()
        worker.register_upstream("http://a:8080", "key-a")
        worker.register_upstream("http://b:8080", "key-b")
        with patch.object(worker, "_start_job"):
            with patch(
                "iris.ingestion.worker.http_requests.post",
                side_effect=[
                    _response(body={"jobs": [{"a": 1}]}),
                    _response(body={"jobs": []}),
                ],
            ) as post:
                worker._claim_once()  # pylint: disable=protected-access
        assert post.call_count == 2
        first, second = post.call_args_list
        assert first.kwargs["json"]["maxJobs"] == 2
        assert second.kwargs["json"]["maxJobs"] == 1

    def test_finished_runs_free_their_slot(self):
        worker = IngestionWorker()
        _run(worker, "done", "http://a:8080", alive=False)
        assert (
            worker._free_slots()  # pylint: disable=protected-access
            == worker._config.capacity  # pylint: disable=protected-access
        )
        assert "done" not in worker._active  # pylint: disable=protected-access


class TestHeartbeat:
    """Heartbeating: active-token reporting, idle upstreams, failure recovery."""

    def test_heartbeat_lists_only_alive_runs_of_the_upstream(self):
        worker = IngestionWorker()
        worker.register_upstream("http://a:8080", "key-a")
        _run(worker, "alive", "http://a:8080")
        _run(worker, "finished", "http://a:8080", alive=False)
        with patch(
            "iris.ingestion.worker.http_requests.post",
            return_value=_response(body={"revokedJobTokens": []}),
        ) as post:
            worker._heartbeat_once()  # pylint: disable=protected-access
        assert post.call_args.kwargs["json"] == {
            "bootId": BOOT_ID,
            "activeJobTokens": ["alive"],
        }

    def test_idle_worker_still_heartbeats_every_upstream(self):
        worker = IngestionWorker()
        worker.register_upstream("http://a:8080", "key-a")
        worker.register_upstream("http://b:8080", "key-b")
        with patch(
            "iris.ingestion.worker.http_requests.post",
            return_value=_response(body={}),
        ) as post:
            worker._heartbeat_once()  # pylint: disable=protected-access
        assert post.call_count == 2
        for call in post.call_args_list:
            assert call.kwargs["json"]["activeJobTokens"] == []

    def test_heartbeat_failure_streak_recovers(self):
        worker = IngestionWorker()
        worker.register_upstream("http://a:8080", "key-a")
        upstream = worker._upstreams[
            "http://a:8080"
        ]  # pylint: disable=protected-access
        import requests as http_requests_module

        with patch(
            "iris.ingestion.worker.http_requests.post",
            side_effect=http_requests_module.exceptions.ConnectionError("down"),
        ):
            worker._heartbeat_once()  # pylint: disable=protected-access
        assert upstream.heartbeat_failures == 1
        with patch(
            "iris.ingestion.worker.http_requests.post",
            return_value=_response(body={}),
        ):
            worker._heartbeat_once()  # pylint: disable=protected-access
        assert upstream.heartbeat_failures == 0


class TestStartJob:
    """_start_job always starts its thread and registers a run in _active for lease
    renewal: add_job supersedes rather than skips, so a reclaimed-lease retry always
    starts and there is no "skipped duplicate" case any more.
    """

    def _start_job(self, worker, upstream_url):
        dto = SimpleNamespace(
            settings=SimpleNamespace(
                authentication_token="tok-12345678",
                artemis_base_url="https://artemis.example",
            ),
            lecture_unit=SimpleNamespace(course_id=1, lecture_id=2, lecture_unit_id=3),
        )
        handler = MagicMock()
        handler.create_cancellation_event.return_value = "cancel-event-sentinel"
        upstream = SimpleNamespace(url=upstream_url)
        with (
            patch(
                "iris.domain.ingestion.ingestion_pipeline_execution_dto"
                ".IngestionPipelineExecutionDto.model_validate",
                return_value=dto,
            ),
            patch("iris.web.utils.validate_pipeline_variant", return_value="variant"),
            patch("iris.web.routers.webhooks.ingestion_job_handler", handler),
            patch(
                "iris.web.routers.webhooks.run_lecture_update_pipeline_worker"
            ) as run_worker,
        ):
            worker._start_job({"job": 1}, upstream)  # pylint: disable=protected-access
        return handler, run_worker

    def test_started_run_is_registered_for_lease_renewal(self):
        worker = IngestionWorker()
        handler, _ = self._start_job(worker, "http://a:8080")
        handler.add_job.assert_called_once()
        assert handler.add_job.call_args.kwargs["base_url"] == "https://artemis.example"
        assert handler.add_job.call_args.kwargs["course_id"] == 1
        assert handler.add_job.call_args.kwargs["lecture_unit_id"] == 3
        assert (
            handler.add_job.call_args.kwargs["cancel_event"] == "cancel-event-sentinel"
        )
        active = worker._active  # pylint: disable=protected-access
        assert "tok-12345678" in active
        assert active["tok-12345678"].upstream_url == "http://a:8080"

    def test_pipeline_thread_receives_the_same_cancel_event_registered_with_add_job(
        self,
    ):
        # The pipeline's own current_job_guard checks this exact cancel_event later; if the
        # thread was built with a different one (or None), a superseding claim could never
        # cancel it. The thread is never actually started here (add_job itself is mocked
        # away), so this inspects the constructor args rather than running it.
        worker = IngestionWorker()
        handler, run_worker = self._start_job(worker, "http://a:8080")
        thread = handler.add_job.call_args.kwargs["process"]
        assert thread._target is run_worker  # pylint: disable=protected-access
        assert (
            thread._args[2] == "cancel-event-sentinel"
        )  # pylint: disable=protected-access

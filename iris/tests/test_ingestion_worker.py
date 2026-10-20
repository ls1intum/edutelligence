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
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests as http_requests_module

from iris.common.boot_id import BOOT_ID
from iris.ingestion.ingestion_job_handler import IngestionJobHandler
from iris.ingestion.worker import IngestionWorker, _ActiveRun


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


def _job(token, unit_id=3):
    """A raw claimed job as Artemis sends it, with just the fields the worker reads."""
    return {
        "settings": {
            "authenticationToken": token,
            "artemisBaseUrl": "https://artemis.example",
        },
        "pyrisLectureUnit": {"lectureUnitId": unit_id, "lectureId": 2, "courseId": 1},
    }


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _heartbeat_and_wait(worker):
    """Run one heartbeat tick and wait for its per-upstream threads to finish."""
    worker._heartbeat_once()  # pylint: disable=protected-access
    assert _wait_for(
        lambda: not worker._heartbeats_in_flight
    )  # pylint: disable=protected-access


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
        jobs = [_job("tok-a"), _job("tok-b", unit_id=4)]
        with patch.object(
            worker,
            "_start_job",
            side_effect=lambda job, pending: started.append(job) or True,
        ):
            with patch(
                "iris.ingestion.worker.http_requests.post",
                return_value=_response(body={"jobs": jobs}),
            ) as post:
                worker._claim_once()  # pylint: disable=protected-access
        assert post.call_args.kwargs["json"] == {
            "bootId": BOOT_ID,
            "maxJobs": worker._config.capacity,  # pylint: disable=protected-access
        }
        assert post.call_args.kwargs["headers"] == {"Authorization": "key-a"}
        assert started == jobs

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
            side_effect=lambda job, pending: started.append(job) or True,
        ):
            with patch(
                "iris.ingestion.worker.http_requests.post",
                return_value=_response(
                    body={
                        "jobs": [
                            _job(f"tok-{i}", unit_id=i)
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
        with patch.object(worker, "_start_job", return_value=True):
            with patch(
                "iris.ingestion.worker.http_requests.post",
                side_effect=[
                    _response(body={"jobs": [_job("tok-a")]}),
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
            _heartbeat_and_wait(worker)
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
            _heartbeat_and_wait(worker)
        assert post.call_count == 2
        for call in post.call_args_list:
            assert call.kwargs["json"]["activeJobTokens"] == []

    def test_revoked_token_signals_the_run_s_cancel_event(self):
        # A revoked lease means Artemis reassigned the unit elsewhere; the
        # local thread can't be killed, but signaling its cancel_event stops
        # it at the pipeline's own existing checkpoints instead of letting it
        # run to completion and possibly clobber the newer run's writes.
        worker = IngestionWorker()
        worker.register_upstream("http://a:8080", "key-a")
        _run(worker, "revoked", "http://a:8080")
        run = worker._active["revoked"]  # pylint: disable=protected-access
        with patch(
            "iris.ingestion.worker.http_requests.post",
            return_value=_response(body={"revokedJobTokens": ["revoked"]}),
        ):
            _heartbeat_and_wait(worker)
        run.cancel_event.set.assert_called_once()

    def test_revoked_token_with_no_matching_active_run_does_not_crash(self):
        # A revocation can arrive after the run already finished and was
        # pruned; there is nothing local left to signal.
        worker = IngestionWorker()
        worker.register_upstream("http://a:8080", "key-a")
        with patch(
            "iris.ingestion.worker.http_requests.post",
            return_value=_response(body={"revokedJobTokens": ["unknown-token"]}),
        ):
            _heartbeat_and_wait(worker)

    def test_heartbeat_failure_streak_recovers(self):
        worker = IngestionWorker()
        worker.register_upstream("http://a:8080", "key-a")
        upstream = worker._upstreams[
            "http://a:8080"
        ]  # pylint: disable=protected-access
        with patch(
            "iris.ingestion.worker.http_requests.post",
            side_effect=http_requests_module.exceptions.ConnectionError("down"),
        ):
            _heartbeat_and_wait(worker)
        assert upstream.heartbeat_failures == 1
        with patch(
            "iris.ingestion.worker.http_requests.post",
            return_value=_response(body={}),
        ):
            _heartbeat_and_wait(worker)
        assert upstream.heartbeat_failures == 0


@contextmanager
def _start_environment(handler):
    """Patch what _start_job imports lazily: variant check, job handler, pipeline worker."""
    with (
        patch("iris.web.utils.validate_pipeline_variant", return_value="variant"),
        patch("iris.web.routers.webhooks.ingestion_job_handler", handler),
        patch(
            "iris.web.routers.webhooks.run_lecture_update_pipeline_worker"
        ) as run_worker,
    ):
        yield run_worker


@contextmanager
def _failure_callbacks(construct_error=None):
    """Replace IngestionStatusCallback; ``reported`` collects (constructor args, message)."""
    reported = []

    class _Callback:
        def __init__(self, run_id, base_url, lecture_unit_id=None):
            if construct_error is not None:
                raise construct_error
            self.args = (run_id, base_url, lecture_unit_id)

        def fail(self, message):
            reported.append((self.args, message))

    with patch(
        "iris.web.status.ingestion_status_callback.IngestionStatusCallback", _Callback
    ):
        yield reported


def _post_router(on_claim=None, on_heartbeat=None):
    """A fake http post that routes claim and heartbeat requests to the given handlers."""

    def post(url, **kwargs):
        handler = on_claim if url.endswith("/claim") else on_heartbeat
        return handler(url, **kwargs)

    return post


class TestStartJob:
    """_start_job always starts its thread and registers a run in _active for lease
    renewal: add_job supersedes rather than skips, so a reclaimed-lease retry always
    starts and there is no "skipped duplicate" case any more.
    """

    def _start_job(self, worker, add_job_result=True, validate_error=None):
        pending = _ActiveRun(
            thread=None,
            upstream_url="http://a:8080",
            lecture_unit_id=3,
            cancel_event=threading.Event(),
        )
        worker._active["tok-12345678"] = pending  # pylint: disable=protected-access
        dto = SimpleNamespace(
            settings=SimpleNamespace(
                authentication_token="tok-12345678",
                artemis_base_url="https://artemis.example",
            ),
            lecture_unit=SimpleNamespace(course_id=1, lecture_id=2, lecture_unit_id=3),
        )
        handler = MagicMock()
        handler.add_job.return_value = add_job_result
        with (
            _start_environment(handler) as run_worker,
            patch(
                "iris.domain.ingestion.ingestion_pipeline_execution_dto"
                ".IngestionPipelineExecutionDto.model_validate",
                return_value=dto,
                side_effect=validate_error,
            ),
        ):
            started = worker._start_job(  # pylint: disable=protected-access
                {"job": 1}, pending
            )
        return handler, run_worker, pending, started

    def test_started_run_is_registered_for_lease_renewal(self):
        worker = IngestionWorker()
        handler, _, pending, started = self._start_job(worker)
        assert started is True
        handler.add_job.assert_called_once()
        assert handler.add_job.call_args.kwargs["base_url"] == "https://artemis.example"
        assert handler.add_job.call_args.kwargs["course_id"] == 1
        assert handler.add_job.call_args.kwargs["lecture_unit_id"] == 3
        active = worker._active  # pylint: disable=protected-access
        assert active["tok-12345678"] is pending
        assert pending.thread is handler.add_job.call_args.kwargs["process"]
        assert pending.upstream_url == "http://a:8080"

    def test_pipeline_thread_receives_the_reserved_cancel_event(self):
        # The pipeline's own current_job_guard checks this exact cancel_event later, and a
        # revocation of the still-pending job sets it; if the thread was built with a
        # different one (or None), neither a superseding claim nor a revocation could
        # cancel it. The thread is never actually started here (add_job itself is mocked
        # away), so this inspects the constructor args rather than running it.
        worker = IngestionWorker()
        handler, run_worker, pending, _ = self._start_job(worker)
        thread = handler.add_job.call_args.kwargs["process"]
        assert thread._target is run_worker  # pylint: disable=protected-access
        assert (
            thread._args[2] is pending.cancel_event
        )  # pylint: disable=protected-access
        assert handler.add_job.call_args.kwargs["cancel_event"] is pending.cancel_event

    def test_job_revoked_before_start_is_dropped_without_a_failure(self):
        worker = IngestionWorker()
        _, _, _, started = self._start_job(worker, add_job_result=False)
        assert started is False
        assert not worker._active  # pylint: disable=protected-access

    def test_start_error_removes_the_reservation_and_reraises(self):
        worker = IngestionWorker()
        with pytest.raises(ValueError, match="invalid"):
            self._start_job(worker, validate_error=ValueError("invalid"))
        assert not worker._active  # pylint: disable=protected-access


class TestBatchStart:
    """One bad job in a claimed batch must not stop the others, and is reported once."""

    def _claim(self, worker, jobs, handler=None):
        worker.register_upstream("http://a:8080", "key-a")
        upstream = worker._upstreams[
            "http://a:8080"
        ]  # pylint: disable=protected-access
        handler = handler or MagicMock()
        with (
            _start_environment(handler),
            patch(
                "iris.ingestion.worker.http_requests.post",
                return_value=_response(body={"jobs": jobs}),
            ),
        ):
            return upstream, worker._claim_from(  # pylint: disable=protected-access
                upstream, len(jobs)
            )

    def test_bad_job_does_not_block_the_good_one_and_is_reported_once(self):
        worker = IngestionWorker()
        # Invalid: the settings lack the Artemis base URL, so validation fails.
        bad = {"settings": {"authenticationToken": "tok-bad"}}
        with _failure_callbacks() as reported:
            upstream, started = self._claim(worker, [bad, _job("tok-good")])
            assert _wait_for(lambda: len(reported) == 1)
        assert started == 1
        assert list(worker._active) == ["tok-good"]  # pylint: disable=protected-access
        (run_id, base_url, _), message = reported[0]
        # No base URL in the job's settings: fall back to the upstream that issued it.
        assert (run_id, base_url) == ("tok-bad", upstream.url)
        assert message

    def test_malformed_raw_jobs_are_survived_without_a_report(self):
        worker = IngestionWorker()
        jobs = [
            "not-a-dict",
            {},
            {"settings": "not-a-dict"},
            {"settings": {}},
            {"settings": {"authenticationToken": ""}},
            {"settings": {"authenticationToken": 5}},
            _job("tok-good"),
        ]
        with _failure_callbacks() as reported:
            _, started = self._claim(worker, jobs)
            # Nothing to report with: none of the broken jobs carries a usable token.
            time.sleep(0.1)
            assert not reported
        assert started == 1
        assert list(worker._active) == ["tok-good"]  # pylint: disable=protected-access

    def test_failing_report_does_not_stop_the_batch(self):
        worker = IngestionWorker()
        bad = {"settings": {"authenticationToken": "tok-bad"}}
        with _failure_callbacks(construct_error=RuntimeError("callback down")):
            _, started = self._claim(worker, [bad, _job("tok-good")])
        assert started == 1
        assert list(worker._active) == ["tok-good"]  # pylint: disable=protected-access

    def test_report_is_dropped_when_the_queue_is_full(self):
        worker = IngestionWorker()
        while worker._failure_slots.acquire(
            blocking=False
        ):  # pylint: disable=protected-access
            pass
        bad = {"settings": {"authenticationToken": "tok-bad"}}
        with _failure_callbacks() as reported:
            _, started = self._claim(worker, [bad, _job("tok-good")])
            time.sleep(0.1)
            assert not reported
        assert started == 1


class TestBatchReservation:
    """A claimed batch is reserved up front, so its leases are renewed while it starts."""

    def test_heartbeat_includes_the_whole_batch_while_the_first_start_blocks(self):
        worker = IngestionWorker()
        worker.register_upstream("http://a:8080", "key-a")
        upstream = worker._upstreams[
            "http://a:8080"
        ]  # pylint: disable=protected-access
        entered, release = threading.Event(), threading.Event()
        handler = MagicMock()
        handler.add_job.side_effect = lambda **_: entered.set() or release.wait(10)
        sent = []
        heartbeat_sent = threading.Event()

        def on_heartbeat(unused_url, **kwargs):
            sent.append(kwargs["json"]["activeJobTokens"])
            heartbeat_sent.set()
            return _response(body={})

        post = _post_router(
            on_claim=lambda *_a, **_k: _response(
                body={"jobs": [_job("tok-1"), _job("tok-2", unit_id=4)]}
            ),
            on_heartbeat=on_heartbeat,
        )
        with (
            _start_environment(handler),
            patch("iris.ingestion.worker.http_requests.post", side_effect=post),
        ):
            claim = threading.Thread(
                target=worker._claim_from,  # pylint: disable=protected-access
                args=(upstream, 2),
            )
            claim.start()
            try:
                assert entered.wait(5)
                # The worker lock must be free while the first job starts.
                beat = threading.Thread(
                    target=worker._heartbeat_once  # pylint: disable=protected-access
                )
                beat.start()
                beat.join(timeout=5)
                assert not beat.is_alive(), "heartbeat blocked on the worker lock"
                assert heartbeat_sent.wait(5)
            finally:
                release.set()
                claim.join(timeout=5)
        assert sorted(sent[0]) == ["tok-1", "tok-2"]

    def test_revoked_pending_job_never_supersedes_a_newer_same_unit_job(self):
        worker = IngestionWorker()
        worker.register_upstream("http://a:8080", "key-a")
        upstream = worker._upstreams[
            "http://a:8080"
        ]  # pylint: disable=protected-access
        handler = IngestionJobHandler()
        first_validating, release = threading.Event(), threading.Event()
        calls = []

        def validate(*_args):
            calls.append(1)
            if len(calls) == 1:
                first_validating.set()
                release.wait(10)
            return "variant"

        post = _post_router(
            on_claim=lambda *_a, **_k: _response(
                body={"jobs": [_job("tok-old"), _job("tok-new")]}
            ),
            on_heartbeat=lambda *_a, **_k: _response(
                body={"revokedJobTokens": ["tok-old"]}
            ),
        )
        with (
            patch("iris.web.utils.validate_pipeline_variant", side_effect=validate),
            patch("iris.web.routers.webhooks.ingestion_job_handler", handler),
            patch(
                "iris.web.routers.webhooks.run_lecture_update_pipeline_worker"
            ) as run_worker,
            patch("iris.ingestion.worker.http_requests.post", side_effect=post),
        ):
            claim = threading.Thread(
                target=worker._claim_from,  # pylint: disable=protected-access
                args=(upstream, 2),
            )
            claim.start()
            try:
                assert first_validating.wait(5)
                old_event = worker._active[  # pylint: disable=protected-access
                    "tok-old"
                ].cancel_event
                _heartbeat_and_wait(worker)
                assert old_event.is_set()
            finally:
                release.set()
                claim.join(timeout=5)
        # The revoked job never started and never cancelled the newer one.
        assert run_worker.call_count == 1
        assert handler._superseded_jobs == 0  # pylint: disable=protected-access
        new_run = worker._active["tok-new"]  # pylint: disable=protected-access
        assert not new_run.cancel_event.is_set()
        assert "tok-old" not in worker._active  # pylint: disable=protected-access
        assert handler.is_current_job(
            "https://artemis.example", 1, 2, 3, new_run.cancel_event
        )


class TestHeartbeatIsolation:
    """One hanging upstream must not delay the heartbeats of the others."""

    def test_hanging_upstreams_do_not_delay_the_healthy_one(self):
        worker = IngestionWorker()
        hanging = [f"http://hang{i}:8080" for i in range(5)]  # more than any pool size
        for url in [*hanging, "http://healthy:8080"]:
            worker.register_upstream(url, "key")
        release = threading.Event()
        posted = []

        def on_heartbeat(url, **_kwargs):
            posted.append(url)
            if "hang" in url:
                release.wait(10)
            return _response(body={})

        post = _post_router(on_heartbeat=on_heartbeat)
        with patch("iris.ingestion.worker.http_requests.post", side_effect=post):
            try:
                worker._heartbeat_once()  # pylint: disable=protected-access
                assert _wait_for(
                    lambda: "http://healthy:8080/api/iris/internal/ingestion/worker/heartbeat"
                    in posted,
                    timeout=2,
                )
            finally:
                release.set()
            assert _wait_for(
                lambda: not worker._heartbeats_in_flight  # pylint: disable=protected-access
            )

    def test_overlapping_tick_skips_an_upstream_still_in_flight(self):
        worker = IngestionWorker()
        worker.register_upstream("http://a:8080", "key-a")
        release = threading.Event()
        posted = []

        def on_heartbeat(url, **_kwargs):
            posted.append(url)
            release.wait(10)
            return _response(body={})

        post = _post_router(on_heartbeat=on_heartbeat)
        with patch("iris.ingestion.worker.http_requests.post", side_effect=post):
            worker._heartbeat_once()  # pylint: disable=protected-access
            assert _wait_for(lambda: len(posted) == 1)
            worker._heartbeat_once()  # pylint: disable=protected-access
            time.sleep(0.1)
            assert len(posted) == 1
            release.set()
            assert _wait_for(
                lambda: not worker._heartbeats_in_flight  # pylint: disable=protected-access
            )
            # Once the first request finished, the next tick heartbeats again.
            _heartbeat_and_wait(worker)
        assert len(posted) == 2

    def test_invalid_json_response_is_handled(self):
        worker = IngestionWorker()
        worker.register_upstream("http://a:8080", "key-a")
        upstream = worker._upstreams[
            "http://a:8080"
        ]  # pylint: disable=protected-access
        response = _response()
        response.json.side_effect = ValueError("not json")
        with patch("iris.ingestion.worker.http_requests.post", return_value=response):
            # Does not raise, and the in-flight mark is cleared for the next tick.
            worker._heartbeats_in_flight.add(  # pylint: disable=protected-access
                upstream.url
            )
            worker._heartbeat_upstream(upstream, [])  # pylint: disable=protected-access
        assert not worker._heartbeats_in_flight  # pylint: disable=protected-access

    def test_heartbeat_uses_its_own_timeout_and_claims_keep_theirs(self):
        worker = IngestionWorker()
        worker.register_upstream("http://a:8080", "key-a")
        with patch(
            "iris.ingestion.worker.http_requests.post",
            return_value=_response(body={"jobs": []}),
        ) as post:
            worker._claim_once()  # pylint: disable=protected-access
            claim_timeout = post.call_args.kwargs["timeout"]
            _heartbeat_and_wait(worker)
            heartbeat_timeout = post.call_args.kwargs["timeout"]
        assert claim_timeout == 30
        assert (
            heartbeat_timeout
            == worker._config.heartbeat_timeout_seconds  # pylint: disable=protected-access
        )

    def test_heartbeat_tick_prunes_expired_upstreams_without_runs(self):
        worker = IngestionWorker()
        worker.register_upstream("http://idle:8080", "key-a")
        worker.register_upstream("http://busy:8080", "key-b")
        _run(worker, "token-busy", "http://busy:8080")
        stale = time.monotonic() - 100_000
        for upstream in worker._upstreams.values():  # pylint: disable=protected-access
            upstream.last_announced_monotonic = stale
        with patch(
            "iris.ingestion.worker.http_requests.post",
            return_value=_response(body={}),
        ) as post:
            _heartbeat_and_wait(worker)
        # The idle one is dropped; the one that still owns a run keeps being renewed.
        assert list(worker._upstreams) == [
            "http://busy:8080"
        ]  # pylint: disable=protected-access
        assert post.call_count == 1
        assert post.call_args.kwargs["json"]["activeJobTokens"] == ["token-busy"]

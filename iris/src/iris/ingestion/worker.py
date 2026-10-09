"""Pull-based ingestion worker with health-check upstream discovery.

Lecture ingestion is a queued batch workload: Artemis holds a full job queue
(state rows, SKIP LOCKED claims, priorities, retry budgets), and this worker is
its consumer, claiming jobs when it has free capacity and renewing a lease for
every run it executes on a fixed short heartbeat interval. Interactive Pyris
features (chat and friends) stay on the push-and-callback pattern; the split
follows workload class, exactly like Artemis's own REST-versus-build-agent
split.

Upstreams are discovered, not configured: every Artemis announces its own base
URL in a header on the authenticated health check it already sends, and the
worker claims from every upstream announced recently. The registry is
in-memory and ephemeral — Iris keeps no standing knowledge of its callers and
no durable state; all queue truth lives in each Artemis's database. An
installation that stops announcing expires out of the registry; a restarted
Iris relearns its upstreams within one health-check interval, during which
each Artemis's push fallback covers dispatch.

The heartbeat is deliberately decoupled from pipeline progress: it is a timer,
not the work, so the lease threshold never has to be sized to the
unpredictable duration of an AI stage. A run whose worker dies stops being
renewed and is reclaimed by its Artemis within seconds; the badge in the
client derives liveness from the same renewals.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit

import requests as http_requests

from iris.common.boot_id import BOOT_ID
from iris.common.logging_config import get_logger
from iris.config import settings

logger = get_logger(__name__)

_REQUEST_TIMEOUT_SECONDS = 30

# An upstream that has not announced itself for this long is no longer claimed
# from. Health checks arrive every few seconds, so this tolerates many missed
# ones; runs already in flight keep being heartbeated until they finish.
_UPSTREAM_EXPIRY_SECONDS = 300.0

# Failure callbacks for jobs that could not start run on a small bounded pool, so a
# slow or unreachable Artemis can never stall the claim loop. When all workers and the
# queue are busy the report is dropped: the Artemis attempt cap is the backstop.
_FAILURE_REPORT_WORKERS = 4
_FAILURE_REPORT_QUEUE = 32


@dataclass
class _Upstream:
    """One discovered Artemis installation and its bookkeeping."""

    url: str
    # The token the upstream authenticated its announcement with; presented
    # back to it on claims and heartbeats. The auth pairing thus comes from the
    # handshake instead of from configuration.
    auth_token: str
    last_announced_monotonic: float
    claim_failures: int = 0
    heartbeat_failures: int = 0


@dataclass
class _ActiveRun:
    """A run this process is executing, and the upstream that owns it.

    A claimed job is reserved here (``thread`` is None) as soon as the claim response
    arrives, so the heartbeat renews its lease while earlier jobs of the same batch are
    still being started. Revoking its token sets ``cancel_event`` before the job starts.
    """

    thread: Optional[threading.Thread]
    upstream_url: str
    lecture_unit_id: Optional[int]
    # The same event the pipeline checks at its existing cancellation
    # checkpoints (current_job_guard / raise_if_cancelled). Retained here so a
    # revocation from Artemis can signal it, the same way a same-worker
    # re-claim already does via add_job's supersession.
    cancel_event: threading.Event


def _job_token(job) -> Optional[str]:
    """The run token of a raw claimed job, or None when the job does not carry a usable one.

    The job is untrusted JSON, so every level is type-checked instead of assumed.
    """
    if not isinstance(job, dict):
        return None
    job_settings = job.get("settings")
    if not isinstance(job_settings, dict):
        return None
    token = job_settings.get("authenticationToken")
    return token if isinstance(token, str) and token else None


def _job_unit_id(job: dict) -> Optional[int]:
    """The lecture unit id of a raw claimed job, or None when it is not present."""
    unit = job.get("pyrisLectureUnit")
    unit_id = unit.get("lectureUnitId") if isinstance(unit, dict) else None
    if unit_id is None:
        unit_id = job.get("lectureUnitId")
    return unit_id if isinstance(unit_id, int) else None


class IngestionWorker:
    """Claims ingestion jobs from all discovered upstreams and heartbeats its runs."""

    def __init__(self):
        self._config = settings.ingestion_worker
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._active: dict[str, _ActiveRun] = {}
        self._upstreams: dict[str, _Upstream] = {}
        self._threads: list[threading.Thread] = []
        self._rotation = 0
        # Upstreams with a heartbeat request in flight; guarded by _lock.
        self._heartbeats_in_flight: set[str] = set()
        self._failure_reporter = ThreadPoolExecutor(
            max_workers=_FAILURE_REPORT_WORKERS,
            thread_name_prefix="ingestion-start-failure",
        )
        self._failure_slots = threading.Semaphore(
            _FAILURE_REPORT_WORKERS + _FAILURE_REPORT_QUEUE
        )

    # ---------------------------------------------------------- discovery

    def register_upstream(self, base_url: str, auth_token: str) -> None:
        """Record an authenticated announcement from an Artemis installation.

        Called from the health endpoint for every request carrying the
        announcement header. Idempotent and cheap: an existing entry only gets
        its freshness and token refreshed.

        Rejects anything that is not a well-formed http(s) URL, and, when
        ``allowed_upstream_hosts`` is configured, anything whose host does not
        match it. A caller that presents a valid API key can otherwise point
        the worker's authenticated outbound requests (claim, heartbeat) at any
        address Iris can reach; this is what stops that without breaking the
        zero-config discovery every unconfigured deployment relies on today.

        :param base_url: the announcing installation's own base URL
        :param auth_token: the api key the announcement authenticated with
        """
        url = base_url.rstrip("/")
        if not url or not self._is_allowed_upstream(url):
            return
        with self._lock:
            existing = self._upstreams.get(url)
            if existing is None:
                logger.info("Discovered Artemis upstream %s via health check", url)
                self._upstreams[url] = _Upstream(
                    url=url,
                    auth_token=auth_token,
                    last_announced_monotonic=time.monotonic(),
                )
            else:
                existing.auth_token = auth_token
                existing.last_announced_monotonic = time.monotonic()

    def _is_allowed_upstream(self, url: str) -> bool:
        """Whether ``url`` is a well-formed http(s) URL and, when an allowlist is configured,
        whose host is in it. Host comparison is case-insensitive and ignores the port, so one
        allowlist entry covers an installation regardless of which port it announces."""
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            logger.warning(
                "Rejected upstream announcement with an invalid URL: %s", url
            )
            return False
        allowed = self._config.allowed_upstream_hosts
        if allowed and parsed.hostname.lower() not in {h.lower() for h in allowed}:
            logger.warning(
                "Rejected upstream announcement from a host not in the allowlist: %s",
                url,
            )
            return False
        return True

    def _drop_expired_upstreams(self, now: float) -> None:
        """Drop upstreams past expiry that own no runs. The caller holds ``_lock``."""
        active_urls = {run.upstream_url for run in self._active.values()}
        expired = [
            url
            for url, upstream in self._upstreams.items()
            if now - upstream.last_announced_monotonic > _UPSTREAM_EXPIRY_SECONDS
            and url not in active_urls
        ]
        for url in expired:
            logger.info("Upstream %s expired from the registry (no announcements)", url)
            del self._upstreams[url]

    def _fresh_upstreams(self) -> list[_Upstream]:
        """Upstreams announced recently, rotated each tick so none starves another.

        Entries past expiry with no active runs are dropped; ones that still
        own runs are kept for heartbeating but no longer claimed from.
        """
        now = time.monotonic()
        with self._lock:
            self._drop_expired_upstreams(now)
            fresh = [
                upstream
                for upstream in self._upstreams.values()
                if now - upstream.last_announced_monotonic <= _UPSTREAM_EXPIRY_SECONDS
            ]
        if not fresh:
            return []
        offset = self._rotation % len(fresh)
        self._rotation += 1
        return fresh[offset:] + fresh[:offset]

    # ------------------------------------------------------------- transport

    def _post(
        self,
        upstream: _Upstream,
        path: str,
        payload: dict,
        timeout: float = _REQUEST_TIMEOUT_SECONDS,
    ) -> http_requests.Response:
        return http_requests.post(
            f"{upstream.url}/api/iris/internal/ingestion/worker/{path}",
            headers={"Authorization": upstream.auth_token},
            json=payload,
            timeout=timeout,
            # Artemis never redirects this endpoint; disabled so a validated upstream cannot be
            # used to reach an address that would not itself have passed _is_allowed_upstream.
            allow_redirects=False,
        )

    # -------------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Start the claim and heartbeat loops as daemon threads."""
        if not self._config.enabled:
            logger.info("Ingestion worker disabled by configuration")
            return
        for name, target in (
            ("ingestion-worker-claim", self._claim_loop),
            ("ingestion-worker-heartbeat", self._heartbeat_loop),
        ):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self._threads.append(thread)
        logger.info(
            "Ingestion worker started (boot_id=%s, capacity=%d), awaiting upstream announcements",
            BOOT_ID,
            self._config.capacity,
        )

    def stop(self) -> None:
        """Signal both loops to stop. Running pipelines finish on their own."""
        self._stop.set()

    # ------------------------------------------------------------ claim loop

    def _free_slots(self) -> int:
        with self._lock:
            self._prune_finished()
            return max(0, self._config.capacity - len(self._active))

    def _prune_finished(self) -> None:
        # A run without a thread is a reserved claim that has not started yet; keep it.
        finished = [
            token
            for token, run in self._active.items()
            if run.thread is not None and not run.thread.is_alive()
        ]
        for token in finished:
            del self._active[token]

    def _claim_loop(self) -> None:
        while not self._stop.wait(self._config.poll_interval_seconds):
            try:
                self._claim_once()
            except Exception as e:  # pylint: disable=broad-exception-caught
                # The loop must survive anything; the next tick is the retry.
                logger.warning("Worker claim tick failed: %s", e)

    def _claim_once(self) -> None:
        slots = self._free_slots()
        if slots == 0:
            return
        for upstream in self._fresh_upstreams():
            if slots == 0:
                return
            slots -= self._claim_from(upstream, slots)

    def _claim_from(self, upstream: _Upstream, slots: int) -> int:
        """Claim up to ``slots`` jobs from one upstream and start them one by one.

        Every claimed job is reserved in ``_active`` before the first one starts, so the
        heartbeat renews the whole batch's leases while the jobs start. A job that fails to
        start is reported as failed and does not stop the rest of the batch. Returns the
        number of jobs that started.
        """
        try:
            response = self._post(
                upstream, "claim", {"bootId": BOOT_ID, "maxJobs": slots}
            )
            response.raise_for_status()
        except http_requests.exceptions.RequestException as e:
            self._log_failure(upstream, "claim", e)
            return 0
        upstream.claim_failures = 0
        jobs = (response.json() or {}).get("jobs") or []
        # The request already asked for at most `slots`; re-clamp the response too, instead of
        # trusting the upstream to honor that limit, since starting more than the requested
        # slots would exceed this worker's own configured capacity.
        claimed = jobs[:slots]
        reserved: list[tuple[dict, Optional[_ActiveRun]]] = []
        with self._lock:
            for job in claimed:
                token = _job_token(job)
                if token is None:
                    reserved.append((job, None))
                    continue
                pending = _ActiveRun(
                    thread=None,
                    upstream_url=upstream.url,
                    lecture_unit_id=_job_unit_id(job),
                    cancel_event=threading.Event(),
                )
                self._active[token] = pending
                reserved.append((job, pending))
        started = 0
        for job, pending in reserved:
            try:
                if pending is None:
                    raise ValueError("claimed job carries no authentication token")
                if self._start_job(job, pending):
                    started += 1
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "Could not start claimed job from %s: %s", upstream.url, e
                )
                self._report_start_failure(job, upstream, e)
        return started

    def _start_job(self, job: dict, pending: _ActiveRun) -> bool:
        """Validate and start one reserved job.

        Returns False when the job was revoked before it started. On any exception the
        reservation is removed and the exception is re-raised for ``_claim_from`` to report.
        """
        # Import here: the webhooks router pulls in the full pipeline stack, and
        # importing it at module load time would create a cycle through main.
        # pylint: disable=import-outside-toplevel
        from iris.domain.ingestion.ingestion_pipeline_execution_dto import (
            IngestionPipelineExecutionDto,
        )
        from iris.pipeline.lecture_ingestion_update_pipeline import (
            LectureIngestionUpdatePipeline,
        )
        from iris.web.routers.webhooks import (
            ingestion_job_handler,
            run_lecture_update_pipeline_worker,
        )
        from iris.web.utils import validate_pipeline_variant

        started = False
        try:
            dto = IngestionPipelineExecutionDto.model_validate(job)
            variant = validate_pipeline_variant(
                dto.settings, LectureIngestionUpdatePipeline
            )
            unit_id = dto.lecture_unit.lecture_unit_id
            # The reserved run's event is the one the pipeline's own current_job_guard checks
            # later, so a reclaimed-lease retry correctly supersedes a still-alive prior run
            # for this unit rather than racing it (see ingestion_job_handler.add_job).
            thread = threading.Thread(
                target=run_lecture_update_pipeline_worker,
                args=(dto, variant, pending.cancel_event),
            )
            if not ingestion_job_handler.add_job(
                process=thread,
                base_url=dto.settings.artemis_base_url,
                course_id=dto.lecture_unit.course_id,
                lecture_id=dto.lecture_unit.lecture_id,
                lecture_unit_id=unit_id,
                cancel_event=pending.cancel_event,
            ):
                logger.info(
                    "Claimed ingestion job for unit %d was revoked before it started",
                    unit_id,
                )
                return False
            with self._lock:
                pending.thread = thread
                pending.lecture_unit_id = unit_id
            started = True
            logger.info(
                "Claimed ingestion job for unit %d from %s",
                unit_id,
                pending.upstream_url,
            )
            return True
        finally:
            if not started:
                with self._lock:
                    for token, run in list(self._active.items()):
                        if run is pending:
                            del self._active[token]

    def _report_start_failure(
        self, job: dict, upstream: _Upstream, error: Exception
    ) -> None:
        """Tell Artemis a claimed job could not start, without ever raising.

        The report runs on a bounded background pool so a slow Artemis cannot stall the
        claim loop. A job without a token cannot be reported and a full queue drops the
        report; either way the attempt cap on the Artemis side ends the retry cycle.
        """
        try:
            token = _job_token(job)
            if token is None:
                logger.warning(
                    "Cannot report the start failure of a claimed job from %s: no token",
                    upstream.url,
                )
                return
            raw_settings = job["settings"]
            base_url = raw_settings.get("artemisBaseUrl")
            if not isinstance(base_url, str) or not base_url:
                base_url = upstream.url
            # pylint: disable=import-outside-toplevel
            from iris.web.status.ingestion_status_callback import (
                IngestionStatusCallback,
            )

            callback = IngestionStatusCallback(
                run_id=token,
                base_url=base_url,
                lecture_unit_id=_job_unit_id(job),
            )
            if not self._failure_slots.acquire(blocking=False):
                logger.warning(
                    "Start-failure report queue is full; dropping the report for a job from %s",
                    upstream.url,
                )
                return
            try:
                future = self._failure_reporter.submit(callback.fail, str(error))
            except BaseException:
                self._failure_slots.release()
                raise
            future.add_done_callback(lambda _: self._failure_slots.release())
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Could not report a start failure for a job from %s: %s",
                upstream.url,
                e,
            )

    # -------------------------------------------------------- heartbeat loop

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self._config.heartbeat_interval_seconds):
            try:
                self._heartbeat_once()
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Worker heartbeat tick failed: %s", e)

    def _heartbeat_once(self) -> None:
        # Every known upstream is heartbeated, with runs or without: the empty
        # heartbeat is what keeps that Artemis in pull mode (push suppressed)
        # while this worker is idle. Expired upstreams that still own runs are
        # included so their leases stay renewed until the runs finish.
        #
        # Each upstream gets its own short-lived thread, so one that hangs delays
        # only its own renewals. An upstream whose previous heartbeat is still in
        # flight is skipped for this tick.
        with self._lock:
            self._prune_finished()
            self._drop_expired_upstreams(time.monotonic())
            tokens_by_url: dict[str, list[str]] = {url: [] for url in self._upstreams}
            for token, run in self._active.items():
                tokens_by_url.setdefault(run.upstream_url, []).append(token)
            due = [
                upstream
                for upstream in self._upstreams.values()
                if upstream.url not in self._heartbeats_in_flight
            ]
            self._heartbeats_in_flight.update(upstream.url for upstream in due)
        for upstream in due:
            try:
                threading.Thread(
                    target=self._heartbeat_upstream,
                    args=(upstream, tokens_by_url.get(upstream.url, [])),
                    name="ingestion-worker-heartbeat-request",
                    daemon=True,
                ).start()
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Could not start a heartbeat to %s: %s", upstream.url, e)
                with self._lock:
                    self._heartbeats_in_flight.discard(upstream.url)

    def _heartbeat_upstream(self, upstream: _Upstream, tokens: list[str]) -> None:
        try:
            self._send_heartbeat(upstream, tokens)
        except Exception as e:  # pylint: disable=broad-exception-caught
            # An unreadable response must not kill the thread silently; the next tick retries.
            logger.warning("Worker heartbeat to %s failed: %s", upstream.url, e)
        finally:
            with self._lock:
                self._heartbeats_in_flight.discard(upstream.url)

    def _send_heartbeat(self, upstream: _Upstream, tokens: list[str]) -> None:
        try:
            response = self._post(
                upstream,
                "heartbeat",
                {"bootId": BOOT_ID, "activeJobTokens": tokens},
                timeout=self._config.heartbeat_timeout_seconds,
            )
            response.raise_for_status()
        except http_requests.exceptions.RequestException as e:
            self._log_failure(upstream, "heartbeat", e)
            return
        if upstream.heartbeat_failures > 0:
            logger.info(
                "Worker heartbeat to %s recovered after %d failures",
                upstream.url,
                upstream.heartbeat_failures,
            )
        upstream.heartbeat_failures = 0
        revoked = (response.json() or {}).get("revokedJobTokens") or []
        for token in revoked:
            # The pipeline thread cannot be killed safely, so it is signaled
            # through the same cancellation event add_job already uses to
            # supersede a same-worker re-claim: the pipeline's existing
            # checkpoints (current_job_guard / raise_if_cancelled) then stop it
            # at the next one, before it writes further. A job still waiting to
            # start is signaled the same way, and add_job then refuses to start
            # it. The run stays in _active (occupying capacity) until its thread
            # actually exits, so a prune can't drop a still-live run; its status
            # callbacks are also rejected by the token check regardless of how
            # quickly it stops.
            with self._lock:
                run = self._active.get(token)
                unit_id = run.lecture_unit_id if run is not None else "unknown"
                if run is not None:
                    run.cancel_event.set()
            logger.warning(
                "%s revoked the run for unit %s — it was reclaimed, signaling the local thread to stop",
                upstream.url,
                unit_id,
            )

    # ------------------------------------------------------------- logging

    def _log_failure(self, upstream: _Upstream, kind: str, error: Exception) -> None:
        # Warn on the first failure of a streak, debug afterwards: an Artemis
        # restart would otherwise produce a warning every interval.
        if kind == "claim":
            upstream.claim_failures += 1
            streak = upstream.claim_failures
        else:
            upstream.heartbeat_failures += 1
            streak = upstream.heartbeat_failures
        log = logger.warning if streak == 1 else logger.debug
        log(
            "Worker %s to %s failed (streak %d): %s",
            kind,
            upstream.url,
            streak,
            error,
        )


ingestion_worker = IngestionWorker()

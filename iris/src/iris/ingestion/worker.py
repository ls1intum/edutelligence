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
from dataclasses import dataclass

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
    """A run this process is executing, and the upstream that owns it."""

    thread: threading.Thread
    upstream_url: str


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

    # ---------------------------------------------------------- discovery

    def register_upstream(self, base_url: str, auth_token: str) -> None:
        """Record an authenticated announcement from an Artemis installation.

        Called from the health endpoint for every request carrying the
        announcement header. Idempotent and cheap: an existing entry only gets
        its freshness and token refreshed.

        :param base_url: the announcing installation's own base URL
        :param auth_token: the api key the announcement authenticated with
        """
        url = base_url.rstrip("/")
        if not url:
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

    def _fresh_upstreams(self) -> list[_Upstream]:
        """Upstreams announced recently, rotated each tick so none starves another.

        Entries past expiry with no active runs are dropped; ones that still
        own runs are kept for heartbeating but no longer claimed from.
        """
        now = time.monotonic()
        with self._lock:
            active_urls = {run.upstream_url for run in self._active.values()}
            expired = [
                url
                for url, upstream in self._upstreams.items()
                if now - upstream.last_announced_monotonic > _UPSTREAM_EXPIRY_SECONDS
                and url not in active_urls
            ]
            for url in expired:
                logger.info(
                    "Upstream %s expired from the registry (no announcements)", url
                )
                del self._upstreams[url]
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
        self, upstream: _Upstream, path: str, payload: dict
    ) -> http_requests.Response:
        return http_requests.post(
            f"{upstream.url}/api/iris/internal/ingestion/worker/{path}",
            headers={"Authorization": upstream.auth_token},
            json=payload,
            timeout=_REQUEST_TIMEOUT_SECONDS,
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
        finished = [
            token for token, run in self._active.items() if not run.thread.is_alive()
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
        """Claim up to ``slots`` jobs from one upstream; returns how many started."""
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
        for job in jobs:
            self._start_job(job, upstream)
        return len(jobs)

    def _start_job(self, job: dict, upstream: _Upstream) -> None:
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

        dto = IngestionPipelineExecutionDto.model_validate(job)
        variant = validate_pipeline_variant(
            dto.settings, LectureIngestionUpdatePipeline
        )
        token = dto.settings.authentication_token
        thread = threading.Thread(
            target=run_lecture_update_pipeline_worker, args=(dto, variant)
        )
        with self._lock:
            self._active[token] = _ActiveRun(thread=thread, upstream_url=upstream.url)
        # The job handler deduplicates per unit exactly like the push webhook.
        ingestion_job_handler.add_job(
            process=thread,
            course_id=dto.lecture_unit.course_id,
            lecture_id=dto.lecture_unit.lecture_id,
            lecture_unit_id=dto.lecture_unit.lecture_unit_id,
        )
        logger.info(
            "Claimed ingestion job for unit %d from %s (token %s...)",
            dto.lecture_unit.lecture_unit_id,
            upstream.url,
            token[:8],
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
        with self._lock:
            self._prune_finished()
            tokens_by_url: dict[str, list[str]] = {url: [] for url in self._upstreams}
            for token, run in self._active.items():
                tokens_by_url.setdefault(run.upstream_url, []).append(token)
            upstreams = list(self._upstreams.values())
        for upstream in upstreams:
            self._heartbeat_upstream(upstream, tokens_by_url.get(upstream.url, []))

    def _heartbeat_upstream(self, upstream: _Upstream, tokens: list[str]) -> None:
        try:
            response = self._post(
                upstream, "heartbeat", {"bootId": BOOT_ID, "activeJobTokens": tokens}
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
            # The pipeline thread cannot be killed safely; it is left to finish,
            # and stays harmless: its status callbacks are rejected by the token
            # check and its vector writes are superseded by the run-id sweep of
            # whichever run owns the unit next.
            logger.warning(
                "%s revoked run %s... — it was reclaimed, letting the local thread drain",
                upstream.url,
                token[:8],
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

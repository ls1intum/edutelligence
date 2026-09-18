"""Batches Logos runs itself.

Not every model can be batched at a provider. A model served by a worker node
has no upstream Batch API at all, and a cloud model can be missing from its
provider's batch offering (Azure adds models to Batch long after Standard, so
the newest ones cannot be batched there for months). Those workloads are the
same workload — many requests, nobody waiting — and researchers should not have
to write a different client for them.

So Logos runs them itself: the input file is stored here, and each request line
is scheduled through the ordinary pipeline at the **lowest queue priority**, so
it fills whatever capacity interactive traffic is not using and finishes as
soon as that capacity exists. Every line is an ordinary request — authorised,
routed, logged and metered exactly like one a client sent — which is why a
Logos-run batch needs no settlement pass afterwards.

The lines run as the capacity frees, in whatever order that is: a long request
does not hold the queue behind it, which is the same order-independence a
provider-executed batch has (its provider schedules the lines however it
likes). The result file is written back in input order, so no caller has to
see the order the lines ran in — and none of the billing, checkpointing or
resuming logic below depends on it either.

The surface is the OpenAI Batch API, unchanged: a script uploads a file, polls
``GET /v1/batches/{id}`` every few minutes, and downloads
``output_file_id`` when the status turns terminal — the same code it would run
against a provider-executed batch, so chaining one batch onto the result of the
last works either way.
"""

import asyncio
import json
import logging
import os
import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from logos.auth import AuthContext
from logos.dbutils.dbmanager import DBManager
from logos.request_content import sanitized_payload_for_logging

logger = logging.getLogger(__name__)

# How many of a batch's request lines are in flight at once. They queue at the
# lowest priority, so this is about not flooding the queue with one batch's
# worth of entries rather than about capacity — the scheduler decides that.
LOCAL_BATCH_CONCURRENCY = int(os.getenv("LOGOS_BATCH_LOCAL_CONCURRENCY", "8"))

# How often the runner looks for batches waiting to be executed.
LOCAL_BATCH_POLL_INTERVAL_S = int(os.getenv("LOGOS_BATCH_LOCAL_POLL_INTERVAL_S", "15"))

# Queue priority a batch line runs at. 1 is LOW on the 1/5/10 scale the
# scheduler uses: batch work yields to everything interactive.
LOCAL_BATCH_PRIORITY = 1

# How long the runner's right to a batch lasts before another process may take
# it over. Refreshed with every chunk of progress, so a live runner holds its
# batch and a dead one's lease runs out; the trade-off is that a batch whose
# runner just died stays paused for up to this long before it is resumed.
LOCAL_BATCH_LEASE_TTL_S = int(os.getenv("LOGOS_BATCH_LEASE_TTL_S", "600"))

_TERMINAL_LOCAL_STATES = {"completed", "failed", "cancelled", "expired"}

# This process, as named in the batch_objects lease. One id per process, so
# the lease tells the database which runner holds a batch.
RUNNER_ID = secrets.token_hex(8)

# Batches currently being run by this process, so a second pass does not start
# one twice within the same orchestrator.
_running: set[int] = set()

# The background tasks this module starts, held for their whole lifetime.
# The event loop keeps only weak references to tasks, so an unheld task can be
# garbage collected while it is still running — which would drop a batch's
# execution mid-file.
_background_tasks: set[asyncio.Task] = set()


def spawn_background(coro, what: str) -> Optional[asyncio.Task]:
    """Run a coroutine in the background, holding the task until it finishes."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # no loop (sync test context): nothing can run
        coro.close()
        logger.debug("No running loop for %s", what)
        return None
    task = loop.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def new_object_id(prefix: str) -> str:
    """An id in the provider-ish shape clients expect (``file-…``/``batch_…``)."""
    separator = "-" if prefix == "file" else "_"
    return f"{prefix}{separator}{secrets.token_hex(12)}"


def auth_context_for_key(api_key_id: int) -> Optional[AuthContext]:
    """Rebuild the submitting key's auth context, at batch priority.

    The runner acts for the key that submitted the batch, long after its
    request is gone. ``default_priority`` is forced to LOW rather than taken
    from the key: a batch is background work even when its owner's interactive
    traffic is not.
    """
    with DBManager() as db:
        row = db.get_api_key_by_id(api_key_id)
    if row is None:
        return None
    key_type = row["key_type"]
    if hasattr(key_type, "value"):
        key_type = key_type.value
    return AuthContext(
        key_value=row["key_value"],
        api_key_id=row["id"],
        api_key_name=row["name"],
        key_type=str(key_type),
        team_id=row["team_id"],
        user_id=row["user_id"],
        environment=row["environment"],
        log_level=row.get("log") or "BILLING",
        settings=row.get("settings") if row.get("settings") is not None else {},
        default_priority=LOCAL_BATCH_PRIORITY,
        # The batch keeps the key's role tiebreak (an application key's batch
        # still beats a developer's within the LOW bucket) and team priority
        # (which stays 0 here — the forced LOW wins the resolution anyway).
        user_role=row.get("role"),
        team_priority=row.get("team_priority") or 0,
    )


def parse_request_lines(content: bytes) -> List[Dict[str, Any]]:
    """The request lines of a validated input file, in order."""
    lines: List[Dict[str, Any]] = []
    for raw_line in (content or b"").splitlines():
        if not raw_line.strip():
            continue
        try:
            line = json.loads(raw_line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(line, dict):
            lines.append(line)
    return lines


def _result_row(line: Dict[str, Any], result: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """One output-file row in the shape the Batch API defines."""
    status_code = int(result.get("status_code") or 500)
    body = result.get("data")
    failed = status_code >= 400
    row: Dict[str, Any] = {
        "id": new_object_id("resp"),
        "custom_id": line.get("custom_id"),
        "response": {"status_code": status_code, "request_id": None, "body": body},
        "error": None,
    }
    if failed:
        # The Batch API reports a failed line in `error`, with the upstream
        # body kept in `response` so the caller can still see what happened.
        message = ""
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            message = str(body["error"].get("message") or "")
        row["error"] = {"code": str(status_code), "message": message or f"request failed with {status_code}"}
    return row, failed


def _open_line_log(auth: AuthContext, body: Dict[str, Any]) -> Optional[int]:
    """Open the usage-log row this request line will be metered into.

    The pipeline writes a response's usage onto an existing ``log_entry``; the
    sync and job paths create it before they call in, and a batch line is no
    different. Without it the request would run and cost money without ever
    reaching the ledger.
    """
    try:
        with DBManager() as db:
            row, code = db.log_usage(
                api_key_id=auth.api_key_id,
                team_id=auth.team_id,
                user_id=auth.user_id,
                environment=auth.environment,
                log_level=auth.log_level,
                client_ip=None,
                input_payload=sanitized_payload_for_logging(body),
                headers=None,
            )
        return int(row["log-id"]) if code == 200 else None
    except Exception:  # noqa: BLE001 - a logging failure must not drop the line
        logger.exception("Could not open a log entry for a batch line")
        return None


async def _run_line(line: Dict[str, Any], auth: AuthContext, headers: Dict[str, str]) -> Tuple[Dict[str, Any], bool]:
    """Run one request line through the ordinary pipeline.

    How many lines run at once is the caller's limit — the runner gives each
    worker of its worker pool exactly one line — not a semaphore inside here,
    so a cancelled worker holds no slot the next line could have taken.
    """
    # Imported here rather than at module scope: main imports the batch modules,
    # so the reverse edge can only be taken once the app is up.
    from logos.main import execute_proxy_job

    endpoint = str(line.get("url") or "").strip("/")
    if not endpoint.startswith("v1/"):
        endpoint = f"v1/{endpoint}"
    body = line.get("body") if isinstance(line.get("body"), dict) else {}

    log_id = _open_line_log(auth, body)
    if log_id is None:
        # Fail closed: without the log row the pipeline would run the
        # request and bill nothing, so the line is refused instead of run
        # unbilled. The batch reports it as a failed line like any other.
        logger.error("No usage log for batch line %s; refusing to run it unbilled", line.get("custom_id"))
        return _result_row(
            line, {"status_code": 500, "data": {"error": {"message": "the request could not be started"}}}
        )
    try:
        result = await execute_proxy_job(endpoint, dict(headers), dict(body), None, auth, log_id)
    except Exception:  # noqa: BLE001 - one bad line must not stop the batch
        # The exception itself stays in the server log; the result file is
        # downloadable by the caller, so it carries a generic message
        # rather than internal details.
        logger.exception("Batch line %s failed", line.get("custom_id"))
        result = {"status_code": 500, "data": {"error": {"message": "the request failed"}}}
    return _result_row(line, result if isinstance(result, dict) else {})


async def run_local_batch(batch: Dict[str, Any]) -> Optional[str]:
    """Execute one Logos-run batch and store its result file.

    Returns the output file id, or None when the batch could not be started.
    """
    batch_object_id = int(batch["id"])
    if batch_object_id in _running:
        return None
    # Claimed before the first await, so two passes of the runner loop in this
    # process cannot both take the same batch. The database claim below is the
    # equivalent guard across processes.
    _running.add(batch_object_id)
    try:
        return await _start(batch, batch_object_id)
    finally:
        _running.discard(batch_object_id)


async def _start(batch: Dict[str, Any], batch_object_id: int) -> Optional[str]:
    """Load a batch's input and hand it to the runner."""
    with DBManager() as db:
        # Every state the runner can take over — queued, or left in_progress
        # by a process that died — goes through the lease claim. It is what
        # keeps two processes from running the same batch: a live lease keeps
        # everyone else out, and an expired one is exactly what makes a dead
        # runner's batch recoverable.
        if not db.claim_local_batch(batch_object_id, RUNNER_ID, LOCAL_BATCH_LEASE_TTL_S):
            return None
        input_object = db.get_local_object_by_upstream_id("file", str(batch["input_file_id"]))
        content = db.get_local_batch_file_content(int(input_object["id"])) if input_object else None

    if content is None:
        logger.error("Batch %s has no readable input file", batch.get("upstream_id"))
        with DBManager() as db:
            db.finish_local_batch(batch_object_id, RUNNER_ID, status="failed")
        return None

    auth = auth_context_for_key(int(batch["api_key_id"])) if batch.get("api_key_id") else None
    if auth is None:
        logger.error("Batch %s was submitted by a key that no longer exists", batch.get("upstream_id"))
        with DBManager() as db:
            db.finish_local_batch(batch_object_id, RUNNER_ID, status="failed")
        return None

    return await _execute_lines(batch_object_id, batch, parse_request_lines(content), auth)


async def _execute_lines(
    batch_object_id: int,
    batch: Dict[str, Any],
    lines: List[Dict[str, Any]],
    auth: AuthContext,
) -> Optional[str]:
    """Run every unfinished line, publishing progress, and write the result file.

    A batch that is resumed after its runner died does not start over: each
    finished line was checkpointed as it completed, and those lines already
    went through the pipeline and were billed, so only the lines without a
    checkpoint are run.

    The lines run on as many workers as there is capacity, a worker taking
    the next line as soon as it is free — not in chunks, where one slow line
    would hold the whole queue behind it until the chunk around it finished.
    That is the same order-independence a provider-executed batch has: the
    lines complete in whatever order the capacity allows, and nothing here
    depends on the order the file spelled them in.
    """
    headers = {"logos_key": auth.key_value}

    with DBManager() as db:
        finished = db.get_local_batch_lines(batch_object_id)
    completed = sum(1 for row in finished.values() if not row.get("error"))
    failed = len(finished) - completed
    pending = [line for line in lines if line.get("custom_id") not in finished]
    cancelled = False

    if pending:
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        for line in pending:
            queue.put_nowait(line)

        # The two ways a run stops short of the last line:
        lost = asyncio.Event()  # lease gone: no checkpoint, no finalization
        no_more = asyncio.Event()  # cancel requested: in-flight lines finish, nothing new starts

        # A single line can legitimately run longer than the whole lease, and
        # a worker sitting in one cannot keep the batch alive on its own, so
        # a heartbeat refreshes the lease while the lines are in flight.
        heartbeat_interval = max(0.2, LOCAL_BATCH_LEASE_TTL_S / 3)
        worker_tasks: List[asyncio.Task] = []

        async def _run_and_checkpoint(line: Dict[str, Any]) -> None:
            """Run one line, make it durable, and publish the progress with it."""
            nonlocal completed, failed, cancelled
            row, line_failed = await _run_line(line, auth, headers)
            if lost.is_set():
                # Deposed mid-line: do not write what the new holder will
                # write again. It resumes past the checkpoint and re-runs
                # this line — which is exactly what must not be billed twice.
                return
            finished[line.get("custom_id")] = row
            if line_failed:
                failed += 1
            else:
                completed += 1
            # Durable per line: that is what makes the resume below skip
            # exactly the lines already run and billed, no matter when the
            # process dies. The progress write joins the checkpoint in one
            # transaction and doubles as a lease heartbeat and a cancel
            # check; it is conditional on the lease — a runner that was
            # deposed must not publish counters the new holder is already
            # moving.
            with DBManager() as db:
                db.save_local_batch_lines(
                    batch_object_id, RUNNER_ID, [{"custom_id": line.get("custom_id"), "row": row}]
                )
                still_running = db.update_local_batch_progress(
                    batch_object_id, RUNNER_ID, completed, failed, LOCAL_BATCH_LEASE_TTL_S
                )
            if still_running is None:
                lost.set()
            elif still_running:
                cancelled = True
                no_more.set()

        async def _worker() -> None:
            while not lost.is_set() and not no_more.is_set():
                try:
                    line = queue.get_nowait()
                except asyncio.QueueEmpty:
                    # Every line is running or finished. All lines were put
                    # in the queue before any worker started, so an empty
                    # queue is the end of the batch, not a pause between
                    # chunks the old design waited through.
                    return
                try:
                    await _run_and_checkpoint(line)
                finally:
                    queue.task_done()

        async def _heartbeat() -> None:
            """Keep the lease alive while lines run, and report a cancel."""
            nonlocal cancelled
            # A None answer — or a check that failed, which fails closed the
            # same way, because a heartbeat that cannot confirm the lease
            # cannot keep it — is the lease being gone: stop the workers
            # before they checkpoint or finalize, and cancel the in-flight
            # lines so the new holder's run of them is not billed twice.
            while not lost.is_set():
                await asyncio.sleep(heartbeat_interval)
                if lost.is_set():
                    return
                try:
                    with DBManager() as db:
                        still = db.update_local_batch_progress(
                            batch_object_id, RUNNER_ID, completed, failed, LOCAL_BATCH_LEASE_TTL_S
                        )
                except Exception:  # noqa: BLE001 - the batch resumes from its checkpoint
                    logger.exception("Lease heartbeat failed for batch %s", batch.get("upstream_id"))
                    still = None
                if still is None:
                    lost.set()
                    for task in worker_tasks:
                        task.cancel()
                    return
                if still:
                    cancelled = True
                    no_more.set()

        # The first progress write is also the first lease check: the claim
        # is the cross-process guard, and this is where a cancel requested
        # before the start reaches this runner.
        with DBManager() as db:
            still_running = db.update_local_batch_progress(
                batch_object_id, RUNNER_ID, completed, failed, LOCAL_BATCH_LEASE_TTL_S
            )
        if still_running is None:
            logger.warning("Lost the lease on batch %s; another runner takes over", batch.get("upstream_id"))
            return None
        if still_running:
            cancelled = True
            no_more.set()

        if not no_more.is_set():
            worker_tasks = [asyncio.ensure_future(_worker()) for _ in range(max(1, LOCAL_BATCH_CONCURRENCY))]
            heartbeat_task = asyncio.ensure_future(_heartbeat())
            try:
                await asyncio.gather(*worker_tasks)
            except asyncio.CancelledError:
                if lost.is_set():
                    logger.warning(
                        "Lost the lease on batch %s mid-run; another runner takes over", batch.get("upstream_id")
                    )
                    return None
                raise
            finally:
                if not heartbeat_task.done():
                    heartbeat_task.cancel()
                # Await the cleanup so the heartbeat cannot outlive the batch:
                # an unawaited, uncancelled task would keep refreshing a lease
                # this runner is done with.
                try:
                    await heartbeat_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001 - its state is in `lost`
                    pass

    rows = [finished[line.get("custom_id")] for line in lines if line.get("custom_id") in finished]
    output_file_id = new_object_id("file")
    content = ("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n").encode() if rows else b""
    with DBManager() as db:
        db.store_local_batch_file(
            upstream_id=output_file_id,
            content=content,
            filename=f"{batch.get('upstream_id')}_output.jsonl",
            api_key_id=batch.get("api_key_id"),
            team_id=batch.get("team_id"),
            user_id=batch.get("user_id"),
            purpose="batch_output",
        )
        finished = db.finish_local_batch(
            batch_object_id,
            RUNNER_ID,
            status="cancelled" if cancelled else "completed",
            output_file_id=output_file_id,
            completed=completed,
            failed=failed,
        )
    if not finished:
        # The lease lapsed before the close-out; the new holder resumes from
        # the checkpoint (every line is written by now) and finalizes the
        # batch. This runner reports no result of its own.
        logger.warning(
            "Lost the lease on batch %s before finalizing; the new holder closes it out", batch.get("upstream_id")
        )
        return None
    logger.info(
        "Local batch %s finished: %d ok, %d failed%s",
        batch.get("upstream_id"),
        completed,
        failed,
        " (cancelled)" if cancelled else "",
    )
    return output_file_id


def local_batch_object(batch: Dict[str, Any]) -> Dict[str, Any]:
    """Render a Logos-run batch as the OpenAI batch object clients expect.

    A polling script must not be able to tell the difference between this and a
    provider's own object, or the two execution paths would need two clients.
    """

    def _epoch(value: Any) -> Optional[int]:
        return int(value.timestamp()) if isinstance(value, datetime) else None

    status = batch.get("status") or "validating"
    created = _epoch(batch.get("created_at"))
    finished = _epoch(batch.get("finished_at"))
    return {
        "id": batch.get("upstream_id"),
        "object": "batch",
        "endpoint": batch.get("endpoint"),
        "errors": None,
        "input_file_id": batch.get("input_file_id"),
        "completion_window": batch.get("completion_window") or "24h",
        "status": status,
        "output_file_id": batch.get("output_file_id"),
        "error_file_id": batch.get("error_file_id"),
        "created_at": created,
        "in_progress_at": _epoch(batch.get("started_at")),
        "expires_at": None,
        "finalizing_at": finished if status == "completed" else None,
        "completed_at": finished if status == "completed" else None,
        "failed_at": finished if status == "failed" else None,
        "expired_at": finished if status == "expired" else None,
        "cancelling_at": None,
        "cancelled_at": finished if status == "cancelled" else None,
        "request_counts": {
            "total": int(batch.get("total_requests") or 0),
            "completed": int(batch.get("completed_requests") or 0),
            "failed": int(batch.get("failed_requests") or 0),
        },
        "metadata": batch.get("request_metadata"),
        # Not part of the OpenAI object: which side ran the job. A client that
        # cares whether it got the provider's batch rate can read it; one that
        # does not can ignore it.
        "logos_execution": "logos",
    }


def local_file_object(file_row: Dict[str, Any]) -> Dict[str, Any]:
    """Render a Logos-held file as the OpenAI file object."""
    created_at = file_row.get("created_at")
    return {
        "id": file_row.get("upstream_id"),
        "object": "file",
        "bytes": int(file_row.get("size_bytes") or 0),
        "created_at": int(created_at.timestamp()) if isinstance(created_at, datetime) else None,
        "filename": file_row.get("filename"),
        "purpose": file_row.get("status") or "batch",
        "logos_execution": "logos",
    }


async def local_batch_runner_loop() -> None:
    """Start every queued Logos-run batch, forever.

    Also offers batches left ``in_progress`` by a process that died mid-file:
    the lease claim lets exactly one runner take each of them over, and it
    resumes from the checkpointed lines rather than re-running the file.
    """
    while True:
        try:
            await asyncio.sleep(LOCAL_BATCH_POLL_INTERVAL_S)
            with DBManager() as db:
                pending = db.get_runnable_local_batches()
            for batch in pending:
                if int(batch["id"]) not in _running:
                    # The claim each run makes decides across processes; this
                    # pass simply offers the batch.
                    spawn_background(run_local_batch(batch), f"local batch {batch.get('upstream_id')}")
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise
        except Exception:  # noqa: BLE001 - the loop outlives its failures
            logger.exception("Local batch runner pass failed")

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

_TERMINAL_LOCAL_STATES = {"completed", "failed", "cancelled", "expired"}

# Batches currently being run by this process, so a second pass does not start
# one twice within the same orchestrator.
_running: set[int] = set()


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


async def _run_line(
    line: Dict[str, Any],
    auth: AuthContext,
    headers: Dict[str, str],
    semaphore: asyncio.Semaphore,
) -> Tuple[Dict[str, Any], bool]:
    """Run one request line through the ordinary pipeline."""
    # Imported here rather than at module scope: main imports the batch modules,
    # so the reverse edge can only be taken once the app is up.
    from logos.main import execute_proxy_job

    endpoint = str(line.get("url") or "").strip("/")
    if not endpoint.startswith("v1/"):
        endpoint = f"v1/{endpoint}"
    body = line.get("body") if isinstance(line.get("body"), dict) else {}

    async with semaphore:
        log_id = _open_line_log(auth, body)
        try:
            result = await execute_proxy_job(endpoint, dict(headers), dict(body), None, auth, log_id)
        except Exception as exc:  # noqa: BLE001 - one bad line must not stop the batch
            logger.exception("Batch line %s failed", line.get("custom_id"))
            result = {"status_code": 500, "data": {"error": {"message": f"{type(exc).__name__}: {exc}"}}}
    return _result_row(line, result if isinstance(result, dict) else {})


async def run_local_batch(batch: Dict[str, Any]) -> Optional[str]:
    """Execute one Logos-run batch and store its result file.

    Returns the output file id, or None when the batch could not be started.
    """
    batch_object_id = int(batch["id"])
    if batch_object_id in _running:
        return None
    with DBManager() as db:
        # in_progress rows are re-offered after a restart, so a batch this
        # process already owns must not be started twice; the conditional
        # claim only lets the first attempt through.
        if batch.get("status") == "validating" and not db.claim_local_batch(batch_object_id):
            return None
        input_object = db.get_local_object_by_upstream_id("file", str(batch["input_file_id"]))
        content = db.get_local_batch_file_content(int(input_object["id"])) if input_object else None

    if content is None:
        logger.error("Batch %s has no readable input file", batch.get("upstream_id"))
        with DBManager() as db:
            db.finish_local_batch(batch_object_id, status="failed")
        return None

    auth = auth_context_for_key(int(batch["api_key_id"])) if batch.get("api_key_id") else None
    if auth is None:
        logger.error("Batch %s was submitted by a key that no longer exists", batch.get("upstream_id"))
        with DBManager() as db:
            db.finish_local_batch(batch_object_id, status="failed")
        return None

    _running.add(batch_object_id)
    try:
        return await _execute_lines(batch_object_id, batch, parse_request_lines(content), auth)
    finally:
        _running.discard(batch_object_id)


async def _execute_lines(
    batch_object_id: int,
    batch: Dict[str, Any],
    lines: List[Dict[str, Any]],
    auth: AuthContext,
) -> Optional[str]:
    """Run every line, publishing progress, and write the result file."""
    headers = {"logos_key": auth.key_value}
    semaphore = asyncio.Semaphore(max(1, LOCAL_BATCH_CONCURRENCY))
    rows: List[Dict[str, Any]] = []
    completed = 0
    failed = 0
    cancelled = False

    # Chunked rather than one gather over the whole file: progress becomes
    # visible while the batch runs, which is what a polling script watches, and
    # a cancel takes effect within a chunk instead of at the end.
    chunk_size = max(1, LOCAL_BATCH_CONCURRENCY)
    for start in range(0, len(lines), chunk_size):
        with DBManager() as db:
            if db.update_local_batch_progress(batch_object_id, completed, failed):
                cancelled = True
                break
        chunk = lines[start : start + chunk_size]
        results = await asyncio.gather(
            *(_run_line(line, auth, headers, semaphore) for line in chunk), return_exceptions=True
        )
        for line, outcome in zip(chunk, results):
            if isinstance(outcome, BaseException):
                logger.exception("Batch line %s raised", line.get("custom_id"), exc_info=outcome)
                row, line_failed = _result_row(line, {"status_code": 500, "data": {"error": {"message": "failed"}}})
            else:
                row, line_failed = outcome
            rows.append(row)
            if line_failed:
                failed += 1
            else:
                completed += 1

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
        db.finish_local_batch(
            batch_object_id,
            status="cancelled" if cancelled else "completed",
            output_file_id=output_file_id,
            completed=completed,
            failed=failed,
        )
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

    Also picks up batches left ``in_progress`` by a process that died mid-file:
    their remaining lines are re-run rather than the batch hanging.
    """
    while True:
        try:
            await asyncio.sleep(LOCAL_BATCH_POLL_INTERVAL_S)
            with DBManager() as db:
                pending = db.get_runnable_local_batches()
            for batch in pending:
                if int(batch["id"]) not in _running:
                    asyncio.create_task(run_local_batch(batch))
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise
        except Exception:  # noqa: BLE001 - the loop outlives its failures
            logger.exception("Local batch runner pass failed")

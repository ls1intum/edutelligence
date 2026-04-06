"""
Replay a scheduling workload CSV (see tests/performance/workloads/README.md) against a running Logos API
instance and aggregate per-request metrics. Generates a detailed CSV plus latency charts.

RECOMMENDED USAGE (shell script wrapper):

    ./tests/performance/test_scheduling_performance.sh \
        --logos-key YourLogosApiKey \
        --workload tests/performance/workloads/explicit/10m/workload_explicit_local5_skewed_bursty_10m.csv \
        --latency-slo-ms 10000

    This script handles Docker container startup, waits for API readiness,
    and persists results to your local repo via volume mounts.

DIRECT PYTHON USAGE (advanced - requires manual Docker setup):

    docker compose exec logos-server poetry run python tests/performance/run_api_workload.py \
        --logos-key YourLogosApiKey \
        --workload tests/performance/workloads/explicit/10m/workload_explicit_local5_skewed_bursty_10m.csv \
        --api-base http://localhost:8080 \
        --latency-slo-ms 10000 \
        --output tests/performance/results/explicit/10m/api_benchmark.csv

For full documentation, see tests/performance/README.md
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from urllib.parse import urlparse

import httpx
from sqlalchemy import text

from logos.dbutils.dbmanager import DBManager

try:
    from .reporting import (
        calculate_percentile,
        generate_overview_charts,
        prepare_distribution_series,
        render_distribution_chart,
        write_distribution_csv,
    )
    from .workload_layouts import count_models_from_payload_rows
except ImportError:
    from reporting import (
        calculate_percentile,
        generate_overview_charts,
        prepare_distribution_series,
        render_distribution_chart,
        write_distribution_csv,
    )
    from workload_layouts import count_models_from_payload_rows


@dataclass(slots=True)
class WorkloadEntry:
    request_id: str
    arrival_offset: float
    mode: str
    priority: str
    body_json: str

    def render_payload(self) -> Dict[str, object]:
        try:
            return json.loads(self.body_json)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"{self.request_id}: body_json column is not valid JSON.") from exc

@dataclass(slots=True)
class RequestResult:
    entry: WorkloadEntry
    status_code: int
    response_body: Optional[dict]
    error: Optional[str]
    duration_ms: float
    server_request_id: Optional[str] = None


DEFAULT_OUTPUT_DIR = Path("tests/performance/results")
WORKLOAD_ROOT_CANDIDATES = (
    Path("tests/performance/workloads"),
    Path("/app/tests/performance/workloads"),
)


@dataclass(slots=True)
class RuntimeArtifacts:
    runtime_samples: list[dict]
    provider_vram: Optional[dict]
    request_log_stats: Optional[dict]


@dataclass(slots=True)
class LogRecord:
    log_id: Optional[int]
    request_id: Optional[str]
    request_ts: datetime
    ttft_ts: Optional[datetime]
    response_ts: Optional[datetime]
    provider_id: Optional[int]
    provider_name: Optional[str]
    model_id: Optional[int]
    model_name: Optional[str]
    response_payload: Optional[dict]
    # Scheduling metrics from log_entry, correlated by request_id
    enqueue_ts: Optional[datetime] = None
    scheduled_ts: Optional[datetime] = None
    complete_ts: Optional[datetime] = None
    cold_start: Optional[bool] = None
    result_status: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    queue_depth_at_arrival: Optional[int] = None
    utilization_at_arrival: Optional[float] = None
    queue_depth_at_schedule: Optional[int] = None
    priority_when_scheduled: Optional[str] = None
    load_duration_ms: Optional[float] = None
    available_vram_mb: Optional[int] = None
    azure_rate_remaining_requests: Optional[int] = None
    azure_rate_remaining_tokens: Optional[int] = None

    @property
    def ttft_ms(self) -> Optional[float]:
        if self.ttft_ts and self.request_ts:
            return (self.ttft_ts - self.request_ts).total_seconds() * 1000
        return None

    @property
    def total_latency_ms(self) -> Optional[float]:
        if self.response_ts and self.request_ts:
            return (self.response_ts - self.request_ts).total_seconds() * 1000
        return None

    @property
    def queue_wait_ms(self) -> Optional[float]:
        """Time spent waiting in queue (enqueue to scheduled)."""
        if self.enqueue_ts and self.scheduled_ts:
            return (self.scheduled_ts - self.enqueue_ts).total_seconds() * 1000
        return None

    @property
    def processing_ms(self) -> Optional[float]:
        """Time spent processing (scheduled to complete)."""
        if self.scheduled_ts and self.complete_ts:
            return (self.complete_ts - self.scheduled_ts).total_seconds() * 1000
        return None

    @property
    def total_time_ms(self) -> Optional[float]:
        """Total time from enqueue to complete."""
        if self.enqueue_ts and self.complete_ts:
            return (self.complete_ts - self.enqueue_ts).total_seconds() * 1000
        return None


@dataclass(slots=True)
class OutputLayout:
    run_dir: Path
    experiment_name: str
    summary_path: Path
    detailed_path: Path
    scenario_manifest_path: Path
    request_response_path: Path
    per_model_summary_path: Path
    latency_distribution_csv_path: Path
    ttft_distribution_csv_path: Path
    latency_distribution_chart_path: Path
    ttft_distribution_chart_path: Path
    runtime_samples_path: Path
    provider_vram_path: Path
    request_log_stats_path: Path
    run_meta_path: Path


def parse_streaming_response(raw_text: str) -> dict:
    content_parts: List[str] = []
    usage: Optional[dict] = None
    final_chunk: Optional[dict] = None
    error_payload: Optional[dict] = None

    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("data:"):
            continue
        data = stripped[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            item = json.loads(data)
        except json.JSONDecodeError:
            continue

        if isinstance(item, dict) and "error" in item:
            error_payload = item
            continue

        if not isinstance(item, dict):
            continue

        final_chunk = item
        item_usage = item.get("usage")
        if isinstance(item_usage, dict):
            usage = item_usage

        for choice in item.get("choices", []):
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if isinstance(delta, dict):
                piece = delta.get("content")
                if isinstance(piece, str):
                    content_parts.append(piece)
            text = choice.get("text")
            if isinstance(text, str):
                content_parts.append(text)

    if error_payload is not None:
        return error_payload

    content = "".join(content_parts)
    if final_chunk is None:
        return {"text": raw_text[:2000]}

    reconstructed = dict(final_chunk)
    reconstructed["choices"] = [{"message": {"role": "assistant", "content": content}}]
    if usage is not None:
        reconstructed["usage"] = usage
    return reconstructed


def _timestamped_run_dir(base_dir: Path, experiment_name: str, timestamp: str) -> Path:
    return base_dir / f"{timestamp} - {experiment_name}"


def default_output_dir_for_workload(workload_path: Path, timestamp: str) -> tuple[Path, str]:
    relative: Optional[Path] = None
    for root in WORKLOAD_ROOT_CANDIDATES:
        try:
            relative = workload_path.relative_to(root)
            break
        except ValueError:
            continue

    if relative is not None:
        output_dir = DEFAULT_OUTPUT_DIR / relative.parent
    else:
        output_dir = DEFAULT_OUTPUT_DIR
    experiment_name = workload_path.stem
    return _timestamped_run_dir(output_dir, experiment_name, timestamp), experiment_name


def resolve_output_layout(output_arg: Optional[Path], workload_path: Path, timestamp: str) -> OutputLayout:
    if output_arg is None:
        run_dir, experiment_name = default_output_dir_for_workload(workload_path, timestamp)
    else:
        experiment_name = output_arg.stem if output_arg.suffix else output_arg.name
        base_dir = output_arg.parent if output_arg.parent != Path("") else DEFAULT_OUTPUT_DIR
        run_dir = _timestamped_run_dir(base_dir, experiment_name, timestamp)

    return OutputLayout(
        run_dir=run_dir,
        experiment_name=experiment_name,
        summary_path=run_dir / "summary.csv",
        detailed_path=run_dir / "detailed.csv",
        scenario_manifest_path=run_dir / "scenario_manifest.json",
        request_response_path=run_dir / "request_response.jsonl",
        per_model_summary_path=run_dir / "per_model_summary.csv",
        latency_distribution_csv_path=run_dir / "latency_distribution.csv",
        ttft_distribution_csv_path=run_dir / "ttft_distribution.csv",
        latency_distribution_chart_path=run_dir / "latency_distribution",
        ttft_distribution_chart_path=run_dir / "ttft_distribution",
        runtime_samples_path=run_dir / "runtime_samples.jsonl",
        provider_vram_path=run_dir / "provider_vram.json",
        request_log_stats_path=run_dir / "request_log_stats.json",
        run_meta_path=run_dir / "run_meta.json",
    )


def isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_headers(logos_key: str) -> dict[str, str]:
    return {
        "logos_key": logos_key,
        "Content-Type": "application/json",
    }


async def _request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    json_body: Optional[dict[str, object]] = None,
) -> dict:
    response = await client.request(method, url, headers=headers, json=json_body)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"{url} returned a non-object JSON payload")
    return payload


async def collect_runtime_samples(
    client: httpx.AsyncClient,
    base_url: str,
    logos_key: str,
    stop_event: asyncio.Event,
    interval_s: float,
) -> list[dict]:
    samples: list[dict] = []
    headers = _json_headers(logos_key)

    async def capture_once() -> None:
        sample: dict[str, object] = {"captured_at": isoformat_utc(datetime.now(timezone.utc))}
        try:
            scheduler_payload = await _request_json(
                client,
                "GET",
                f"{base_url.rstrip('/')}/logosdb/scheduler_state",
                headers=headers,
            )
            sample["scheduler_state"] = scheduler_payload
            provider_ids: list[int] = []
            logosnode = scheduler_payload.get("logosnode")
            if isinstance(logosnode, dict):
                providers = logosnode.get("providers")
                if isinstance(providers, dict):
                    provider_ids = [
                        int(provider_id)
                        for provider_id in providers.keys()
                        if str(provider_id).isdigit()
                    ]

            provider_status: dict[str, object] = {}
            for provider_id in provider_ids:
                try:
                    provider_status[str(provider_id)] = await _request_json(
                        client,
                        "POST",
                        f"{base_url.rstrip('/')}/logosdb/providers/logosnode/status",
                        headers=headers,
                        json_body={"logos_key": logos_key, "provider_id": provider_id},
                    )
                except Exception as exc:  # noqa: BLE001
                    provider_status[str(provider_id)] = {"error": str(exc)}
            sample["provider_status"] = provider_status
        except Exception as exc:  # noqa: BLE001
            sample["error"] = str(exc)
        samples.append(sample)

    await capture_once()
    while True:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
            break
        except asyncio.TimeoutError:
            await capture_once()

    await capture_once()
    return samples


def _request_json_sync(
    method: str,
    url: str,
    *,
    logos_key: str,
    json_body: Optional[dict[str, object]] = None,
    timeout_s: float = 30.0,
) -> Optional[dict]:
    try:
        response = httpx.request(
            method,
            url,
            headers=_json_headers(logos_key),
            json=json_body,
            timeout=timeout_s,
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else None
    except Exception:  # noqa: BLE001
        return None


def fetch_runtime_artifacts(
    base_url: str,
    logos_key: str,
    *,
    start_ts: datetime,
    end_ts: datetime,
    runtime_samples: list[dict],
) -> RuntimeArtifacts:
    vram_day = start_ts.astimezone(timezone.utc).date().isoformat()
    provider_vram = _request_json_sync(
        "POST",
        f"{base_url.rstrip('/')}/logosdb/get_ollama_vram_stats",
        logos_key=logos_key,
        json_body={"day": vram_day},
    )
    request_log_stats = _request_json_sync(
        "POST",
        f"{base_url.rstrip('/')}/logosdb/request_log_stats",
        logos_key=logos_key,
        json_body={
            "start_date": isoformat_utc(start_ts),
            "end_date": isoformat_utc(end_ts),
            "target_buckets": 120,
        },
    )
    return RuntimeArtifacts(
        runtime_samples=runtime_samples,
        provider_vram=provider_vram,
        request_log_stats=request_log_stats,
    )


def extract_load_duration_ms(payload: Optional[dict]) -> Optional[float]:
    if payload is None or not isinstance(payload, dict):
        return None

    usage = payload.get("usage")
    raw = usage.get("load_duration") if isinstance(usage, dict) else None
    if raw is None:
        raw = payload.get("load_duration")
    if raw is None:
        return None

    try:
        numeric = float(raw)
    except (TypeError, ValueError):
        return None

    if numeric > 1_000_000:
        return numeric / 1_000_000.0
    return numeric


async def dispatch_request(
    client: httpx.AsyncClient,
    base_url: str,
    logos_key: str,
    entry: WorkloadEntry,
    start_monotonic: float,
) -> RequestResult:
    # Convert arrival_offset from milliseconds to seconds, then calculate wait time
    wait = (entry.arrival_offset / 1000.0) - (asyncio.get_event_loop().time() - start_monotonic)
    if wait > 0:
        await asyncio.sleep(wait)

    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    payload = entry.render_payload()
    headers = {"logos_key": logos_key, "Content-Type": "application/json"}

    start = time.perf_counter()
    try:
        if payload.get("stream") is True:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                raw_text = await response.aread()
                duration_ms = (time.perf_counter() - start) * 1000
                body = parse_streaming_response(raw_text.decode("utf-8", errors="replace"))
                status_code = response.status_code
                server_request_id = response.headers.get("X-Request-ID") or response.headers.get("x-request-id")
        else:
            response = await client.request(
                "POST",
                url,
                json=payload,
                headers=headers,
            )
            duration_ms = (time.perf_counter() - start) * 1000
            try:
                body = response.json()
            except json.JSONDecodeError:
                body = {"text": response.text}
            status_code = response.status_code
            server_request_id = response.headers.get("X-Request-ID") or response.headers.get("x-request-id")
        error = None if status_code < 400 else body
        return RequestResult(
            entry=entry,
            status_code=status_code,
            response_body=body,
            error=None if error is None else json.dumps(error)[:500],
            duration_ms=duration_ms,
            server_request_id=server_request_id,
        )
    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        return RequestResult(
            entry=entry,
            status_code=0,
            response_body=None,
            error=str(exc),
            duration_ms=duration_ms,
        )


def parse_workload(path: Path) -> List[WorkloadEntry]:
    entries: List[WorkloadEntry] = []
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("Workload CSV is missing a header row.")
        normalized_headers: List[str] = []
        seen_headers: set[str] = set()
        for header in reader.fieldnames:
            if header is None:
                continue
            normalized = header.strip().lower()
            if normalized in seen_headers:
                raise ValueError(f"Workload file contains duplicate column when ignoring case: {header}")
            normalized_headers.append(normalized)
            seen_headers.add(normalized)
        reader.fieldnames = normalized_headers
        required = {"arrival_offset", "body_json"}
        missing = required - set(reader.fieldnames)
        if missing:
            raise ValueError(f"Workload file is missing required columns: {', '.join(sorted(missing))}")
        for idx, row in enumerate(reader, start=1):
            request_id = row.get("request_id") or f"req-{idx}"
            try:
                offset = float(row["arrival_offset"])
            except ValueError as exc:
                raise ValueError(f"Invalid arrival_offset for row {idx}: {row['arrival_offset']}") from exc

            body_json = row.get("body_json")
            if not body_json:
                raise ValueError(f"Row {idx}: body_json is required and cannot be empty")

            # Parse mode (optional, default to "interactive")
            mode = row.get("mode", "interactive").strip().lower()
            if mode not in ("interactive", "batch"):
                raise ValueError(f"Row {idx}: mode must be 'interactive' or 'batch', got '{mode}'")

            # Parse priority (optional, default to "mid")
            priority = row.get("priority", "mid").strip().lower()
            if priority not in ("low", "mid", "high"):
                raise ValueError(f"Row {idx}: priority must be 'low', 'mid', or 'high', got '{priority}'")

            entries.append(
                WorkloadEntry(
                    request_id=request_id,
                    arrival_offset=offset,
                    mode=mode,
                    priority=priority,
                    body_json=body_json,
                )
            )
    entries.sort(key=lambda e: (e.arrival_offset, e.request_id))
    return entries


def infer_workload_scenario_manifest(workload_path: Path, entries: Sequence[WorkloadEntry]) -> dict:
    model_counts = count_models_from_payload_rows(
        [{"body_json": entry.body_json} for entry in entries]
    )
    max_offset = max((entry.arrival_offset for entry in entries), default=0.0)
    duration_ms = int(max_offset) + 1 if entries else 0
    return {
        "scenario_name": workload_path.stem,
        "layout": "legacy",
        "duration_ms": duration_ms,
        "total_requests": len(entries),
        "seed": None,
        "model_counts": model_counts,
    }


def load_workload_scenario_manifest(workload_path: Path, entries: Sequence[WorkloadEntry]) -> dict:
    manifest_path = workload_path.with_suffix(".json")
    if manifest_path.exists():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass
    return infer_workload_scenario_manifest(workload_path, entries)


def fetch_process_metadata(logos_key: str) -> tuple[int, str]:
    with DBManager() as db:
        result, status = db.get_process_id(logos_key)
        if status != 200:
            raise RuntimeError(f"Unknown logos key; database returned {result}")
        process_id = int(result["result"])
        current_log = db.log(process_id)
        return process_id, current_log


def set_log_level(process_id: int, level: str) -> None:
    with DBManager() as db:
        db.set_process_log(process_id, level)


def current_log_max(process_id: int) -> int:
    with DBManager() as db:
        value = db.session.execute(
            text("SELECT COALESCE(MAX(id), 0) FROM log_entry WHERE process_id = :pid"),
            {"pid": process_id},
        ).scalar()
        return int(value or 0)


def is_local_api_base(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    return host in {"", "localhost", "127.0.0.1", "0.0.0.0"}


def fetch_log_records(process_id: int, start_log_id: int) -> List[LogRecord]:
    with DBManager() as db:
        rows = db.session.execute(
            text(
                """
                SELECT
                    le.id,
                    le.request_id,
                    le.timestamp_request,
                    le.timestamp_forwarding,
                    le.time_at_first_token,
                    le.timestamp_response,
                    le.provider_id,
                    providers.name AS provider_name,
                    le.model_id,
                    models.name AS model_name,
                    le.response_payload,
                    le.was_cold_start,
                    le.result_status,
                    le.queue_depth_at_arrival,
                    le.utilization_at_arrival,
                    le.queue_depth_at_schedule,
                    le.priority_when_scheduled,
                    le.load_duration_ms,
                    le.available_vram_mb,
                    le.azure_rate_remaining_requests,
                    le.azure_rate_remaining_tokens
                FROM log_entry le
                LEFT JOIN providers ON le.provider_id = providers.id
                LEFT JOIN models ON le.model_id = models.id
                WHERE le.process_id = :pid
                  AND le.id > :start_id
                ORDER BY le.id ASC
                """
            ),
            {"pid": process_id, "start_id": start_log_id},
        ).fetchall()

    records: List[LogRecord] = []
    for row in rows:
        payload = row.response_payload
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {"text": payload}
        records.append(
            LogRecord(
                log_id=row.id,
                request_id=row.request_id,
                request_ts=row.timestamp_request,
                ttft_ts=row.time_at_first_token,
                response_ts=row.timestamp_response,
                provider_id=row.provider_id,
                provider_name=row.provider_name,
                model_id=row.model_id,
                model_name=row.model_name,
                response_payload=payload,
                enqueue_ts=row.timestamp_request,
                scheduled_ts=row.timestamp_forwarding,
                complete_ts=row.timestamp_response,
                cold_start=row.was_cold_start,
                result_status=row.result_status,
                queue_depth_at_arrival=row.queue_depth_at_arrival,
                utilization_at_arrival=float(row.utilization_at_arrival) if row.utilization_at_arrival is not None else None,
                queue_depth_at_schedule=row.queue_depth_at_schedule,
                priority_when_scheduled=row.priority_when_scheduled,
                load_duration_ms=float(row.load_duration_ms) if row.load_duration_ms is not None else None,
                available_vram_mb=row.available_vram_mb,
                azure_rate_remaining_requests=row.azure_rate_remaining_requests,
                azure_rate_remaining_tokens=row.azure_rate_remaining_tokens,
            )
        )
    return records


def extract_response_text(payload: Optional[dict]) -> Optional[str]:
    if payload is None:
        return None
    if isinstance(payload, dict):
        if "choices" in payload and isinstance(payload["choices"], list):
            snippets: List[str] = []
            for choice in payload["choices"]:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if content:
                        snippets.append(content if isinstance(content, str) else json.dumps(content))
                        continue
                delta = choice.get("delta")
                if isinstance(delta, dict):
                    content = delta.get("content")
                    if content:
                        snippets.append(content if isinstance(content, str) else json.dumps(content))
                        continue
                text = choice.get("text")
                if isinstance(text, str):
                    snippets.append(text)
            if snippets:
                return "".join(snippets)
        for key in ("output_text", "content", "result", "text"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
    return json.dumps(payload, ensure_ascii=False)[:500]


def extract_token_count(payload: Optional[dict]) -> Optional[int]:
    """Extract completion token count from response payload."""
    if payload is None or not isinstance(payload, dict):
        return None

    # OpenAI-style usage field
    usage = payload.get("usage")
    if isinstance(usage, dict):
        completion_tokens = usage.get("completion_tokens")
        if isinstance(completion_tokens, int):
            return completion_tokens

    # Alternative fields
    for key in ("output_tokens", "tokens_generated", "num_tokens", "eval_count", "completion_tokens"):
        value = payload.get(key)
        if isinstance(value, int):
            return value

    return None


def extract_usage_counts(payload: Optional[dict]) -> tuple[Optional[int], Optional[int], Optional[int]]:
    if payload is None or not isinstance(payload, dict):
        return None, None, None

    usage = payload.get("usage")
    if isinstance(usage, dict):
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")
        return (
            prompt_tokens if isinstance(prompt_tokens, int) else None,
            completion_tokens if isinstance(completion_tokens, int) else None,
            total_tokens if isinstance(total_tokens, int) else None,
        )

    return None, None, None


def fetch_request_logs_via_api(
    base_url: str,
    logos_key: str,
    request_ids: Sequence[str],
    timeout_s: float,
) -> Dict[str, LogRecord]:
    normalized_ids = []
    seen_ids = set()
    for request_id in request_ids:
        value = str(request_id or "").strip()
        if not value or value in seen_ids:
            continue
        normalized_ids.append(value)
        seen_ids.add(value)

    if not normalized_ids:
        return {}

    url = f"{base_url.rstrip('/')}/logosdb/request_logs"
    headers = {"logos_key": logos_key, "Content-Type": "application/json"}
    response = httpx.post(url, headers=headers, json={"request_ids": normalized_ids}, timeout=timeout_s)
    response.raise_for_status()
    payload = response.json()

    records: Dict[str, LogRecord] = {}
    for item in payload.get("requests", []):
        request_id = item.get("request_id")
        request_ts = item.get("enqueue_ts")
        if not request_id or not request_ts:
            continue
        records[request_id] = LogRecord(
            log_id=None,
            request_id=request_id,
            request_ts=datetime.fromisoformat(request_ts.replace("Z", "+00:00")),
            ttft_ts=datetime.fromisoformat(item["enqueue_ts"].replace("Z", "+00:00")) + timedelta(milliseconds=float(item["ttft_ms"]))
            if item.get("ttft_ms") is not None
            else None,
            response_ts=datetime.fromisoformat(item["request_complete_ts"].replace("Z", "+00:00"))
            if item.get("request_complete_ts")
            else None,
            provider_id=None,
            provider_name=item.get("provider_name"),
            model_id=None,
            model_name=item.get("model_name"),
            response_payload=None,
            enqueue_ts=datetime.fromisoformat(item["enqueue_ts"].replace("Z", "+00:00"))
            if item.get("enqueue_ts")
            else None,
            scheduled_ts=datetime.fromisoformat(item["scheduled_ts"].replace("Z", "+00:00"))
            if item.get("scheduled_ts")
            else None,
            complete_ts=datetime.fromisoformat(item["request_complete_ts"].replace("Z", "+00:00"))
            if item.get("request_complete_ts")
            else None,
            cold_start=item.get("cold_start"),
            result_status=item.get("status"),
            prompt_tokens=item.get("prompt_tokens"),
            completion_tokens=item.get("completion_tokens"),
            total_tokens=item.get("total_tokens"),
            queue_depth_at_arrival=item.get("queue_depth_at_arrival"),
            utilization_at_arrival=float(item["utilization_at_arrival"])
            if item.get("utilization_at_arrival") is not None
            else None,
            queue_depth_at_schedule=item.get("queue_depth_at_schedule"),
            priority_when_scheduled=item.get("priority_when_scheduled"),
            load_duration_ms=float(item["load_duration_ms"]) if item.get("load_duration_ms") is not None else None,
            available_vram_mb=item.get("available_vram_mb"),
            azure_rate_remaining_requests=item.get("azure_rate_remaining_requests"),
            azure_rate_remaining_tokens=item.get("azure_rate_remaining_tokens"),
        )
    return records


def wait_for_request_logs_via_api(
    base_url: str,
    logos_key: str,
    request_ids: Sequence[str],
    timeout: float = 30.0,
    poll_interval: float = 1.0,
) -> Dict[str, LogRecord]:
    deadline = time.monotonic() + timeout
    last_records: Dict[str, LogRecord] = {}
    expected = {str(request_id).strip() for request_id in request_ids if str(request_id).strip()}
    while True:
        last_records = fetch_request_logs_via_api(base_url, logos_key, list(expected), timeout_s=max(5.0, poll_interval + 5.0))
        if expected.issubset(last_records.keys()) or time.monotonic() >= deadline:
            return last_records
        time.sleep(poll_interval)


def build_rows(
    results: Sequence[RequestResult],
    logs: Sequence[LogRecord] | Dict[str, LogRecord],
    latency_slo_ms: float,
    *,
    scenario_name: str | None = None,
) -> tuple[Dict[str, object], List[Dict[str, object]], int]:
    detail_records: List[Dict[str, object]] = []
    ttft_values: List[float] = []
    tpot_values: List[float] = []
    latency_values: List[float] = []
    queue_wait_values: List[float] = []
    processing_values: List[float] = []
    scheduler_total_values: List[float] = []
    successes = 0

    log_by_request_id = logs if isinstance(logs, dict) else {
        log.request_id: log for log in logs if isinstance(log.request_id, str) and log.request_id
    }
    use_request_ids = isinstance(logs, dict) or any(result.server_request_id for result in results)
    missing_logs = 0

    if use_request_ids:
        result_log_pairs = []
        for result in results:
            log = log_by_request_id.get(result.server_request_id or "")
            if log is None:
                missing_logs += 1
            result_log_pairs.append((result, log))
    else:
        missing_logs = max(0, len(results) - len(logs))
        padded_logs: List[Optional[LogRecord]] = list(logs[: len(results)]) + [None] * missing_logs
        result_log_pairs = list(zip(results, padded_logs))

    for result, log in result_log_pairs:
        ttft: Optional[float] = None
        total_latency: Optional[float] = None
        provider_id: Optional[int] = None
        provider_name: Optional[str] = None
        model_id: Optional[int] = None
        model_name: Optional[str] = None
        response_text: Optional[str] = None
        response_body_json: Optional[str] = None
        log_id: Optional[int] = None
        tokens: Optional[int] = None
        tpot: Optional[float] = None
        queue_wait: Optional[float] = None
        processing_ms: Optional[float] = None
        scheduler_total: Optional[float] = None
        cold_start: Optional[bool] = None
        result_status: Optional[str] = None
        prompt_tokens: Optional[int] = None
        completion_tokens: Optional[int] = None
        total_tokens: Optional[int] = None
        queue_depth_at_arrival: Optional[int] = None
        utilization_at_arrival: Optional[float] = None
        queue_depth_at_schedule: Optional[int] = None
        priority_when_scheduled: Optional[str] = None
        load_duration_ms: Optional[float] = None
        available_vram_mb: Optional[int] = None
        azure_rate_remaining_requests: Optional[int] = None
        azure_rate_remaining_tokens: Optional[int] = None
        total_tokens_per_second: Optional[float] = None
        completion_tokens_per_second: Optional[float] = None
        request_ts_utc: Optional[str] = None
        ttft_ts_utc: Optional[str] = None
        response_ts_utc: Optional[str] = None

        if log is not None:
            ttft = log.ttft_ms
            total_latency = log.total_latency_ms
            queue_wait = log.queue_wait_ms
            processing_ms = log.processing_ms
            scheduler_total = log.total_time_ms
            provider_id = log.provider_id
            provider_name = log.provider_name
            model_id = log.model_id
            model_name = log.model_name
            response_text = extract_response_text(log.response_payload)
            response_body_json = json.dumps(log.response_payload, ensure_ascii=False)[:2000] if log.response_payload is not None else None
            tokens = extract_token_count(log.response_payload)
            if tokens is None:
                tokens = log.completion_tokens or log.total_tokens
            log_id = log.log_id
            cold_start = log.cold_start
            result_status = log.result_status
            prompt_tokens = log.prompt_tokens
            completion_tokens = log.completion_tokens
            total_tokens = log.total_tokens
            queue_depth_at_arrival = log.queue_depth_at_arrival
            utilization_at_arrival = log.utilization_at_arrival
            queue_depth_at_schedule = log.queue_depth_at_schedule
            priority_when_scheduled = log.priority_when_scheduled
            load_duration_ms = log.load_duration_ms
            available_vram_mb = log.available_vram_mb
            azure_rate_remaining_requests = log.azure_rate_remaining_requests
            azure_rate_remaining_tokens = log.azure_rate_remaining_tokens
            request_ts_utc = log.request_ts.isoformat() if log.request_ts is not None else None
            ttft_ts_utc = log.ttft_ts.isoformat() if log.ttft_ts is not None else None
            response_ts_utc = log.response_ts.isoformat() if log.response_ts is not None else None
            if prompt_tokens is None or completion_tokens is None or total_tokens is None:
                payload_prompt_tokens, payload_completion_tokens, payload_total_tokens = extract_usage_counts(log.response_payload)
                prompt_tokens = prompt_tokens if prompt_tokens is not None else payload_prompt_tokens
                completion_tokens = completion_tokens if completion_tokens is not None else payload_completion_tokens
                total_tokens = total_tokens if total_tokens is not None else payload_total_tokens
            if load_duration_ms is None:
                load_duration_ms = extract_load_duration_ms(log.response_payload)

            # Calculate TPOT (Time Per Output Token)
            if ttft is not None and total_latency is not None and tokens is not None and tokens > 1:
                tpot = (total_latency - ttft) / (tokens - 1)
            if total_latency is not None and total_latency > 0 and total_tokens is not None:
                total_tokens_per_second = total_tokens / (total_latency / 1000.0)
            if (
                ttft is not None
                and total_latency is not None
                and total_latency > ttft
                and completion_tokens is not None
            ):
                completion_tokens_per_second = completion_tokens / ((total_latency - ttft) / 1000.0)

            if ttft is not None:
                ttft_values.append(ttft)
            if tpot is not None:
                tpot_values.append(tpot)
            if total_latency is not None:
                latency_values.append(total_latency)
            if queue_wait is not None:
                queue_wait_values.append(queue_wait)
            if processing_ms is not None:
                processing_values.append(processing_ms)
            if scheduler_total is not None:
                scheduler_total_values.append(scheduler_total)

        if result.status_code and result.status_code < 400:
            successes += 1

        request_payload = result.entry.render_payload()
        raw_response_payload = log.response_payload if log is not None else result.response_body
        error_text = result.error
        if response_body_json is None and result.response_body is not None:
            response_body_json = json.dumps(result.response_body, ensure_ascii=False)[:2000]
        if response_text is None and result.response_body is not None:
            response_text = extract_response_text(result.response_body)
        if load_duration_ms is None and result.response_body is not None:
            load_duration_ms = extract_load_duration_ms(result.response_body)
        if log is None:
            note = "log entry missing"
            error_text = f"{result.error} | {note}" if result.error else note

        record = {
            "log_id": log_id,
            "request_id": result.entry.request_id,
            "server_request_id": result.server_request_id,
            "scenario_name": scenario_name,
            "arrival_offset_ms": result.entry.arrival_offset,
            "mode": result.entry.mode,
            "priority": result.entry.priority,
            "priority_when_scheduled": priority_when_scheduled,
            "http_status": result.status_code,
            "client_duration_ms": result.duration_ms,
            "request_body_json": result.entry.body_json,
            "provider_id": provider_id,
            "provider_name": provider_name,
            "model_id": model_id,
            "model_name": model_name,
            "cold_start": cold_start,
            "load_duration_ms": load_duration_ms,
            "result_status": result_status,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "total_tokens_per_second": total_tokens_per_second,
            "completion_tokens_per_second": completion_tokens_per_second,
            "ttft_ms": ttft,
            "tpot_ms": tpot,
            "tokens": tokens,
            "total_latency_ms": total_latency,
            "queue_depth_at_arrival": queue_depth_at_arrival,
            "utilization_at_arrival": utilization_at_arrival,
            "queue_depth_at_schedule": queue_depth_at_schedule,
            "queue_wait_ms": queue_wait,
            "processing_ms": processing_ms,
            "scheduler_total_ms": scheduler_total,
            "request_ts_utc": request_ts_utc,
            "ttft_ts_utc": ttft_ts_utc,
            "response_ts_utc": response_ts_utc,
            "available_vram_mb": available_vram_mb,
            "azure_rate_remaining_requests": azure_rate_remaining_requests,
            "azure_rate_remaining_tokens": azure_rate_remaining_tokens,
            "_request_ts": log.request_ts if log is not None else None,
            "_response_ts": log.response_ts if log is not None else None,
            "_request_payload": request_payload,
            "_response_payload": raw_response_payload,
            "response_body_json": response_body_json,
            "response_text": response_text,
            "error": error_text,
        }
        if not result.server_request_id:
            note = "missing_request_id_header"
            record["error"] = f"{record['error']} | {note}" if record["error"] else note
        elif use_request_ids and log is None:
            note = "log entry missing"
            record["error"] = f"{record['error']} | {note}" if record["error"] else note
        detail_records.append(record)

    total_requests = len(results)
    errors = total_requests - successes
    error_rate = (errors / total_requests * 100) if total_requests else math.nan

    slo_hits = sum(1 for latency in latency_values if latency <= latency_slo_ms)
    slo_attainment_rate = (slo_hits / len(latency_values) * 100) if latency_values else math.nan

    # Calculate statistics
    avg_ttft = sum(ttft_values) / len(ttft_values) if ttft_values else math.nan
    p50_ttft = calculate_percentile(ttft_values, 50)
    p95_ttft = calculate_percentile(ttft_values, 95)
    p99_ttft = calculate_percentile(ttft_values, 99)

    avg_tpot = sum(tpot_values) / len(tpot_values) if tpot_values else math.nan
    p50_tpot = calculate_percentile(tpot_values, 50)
    p95_tpot = calculate_percentile(tpot_values, 95)
    p99_tpot = calculate_percentile(tpot_values, 99)

    avg_latency = sum(latency_values) / len(latency_values) if latency_values else math.nan
    p50_latency = calculate_percentile(latency_values, 50)
    p95_latency = calculate_percentile(latency_values, 95)
    p99_latency = calculate_percentile(latency_values, 99)

    avg_queue_wait = sum(queue_wait_values) / len(queue_wait_values) if queue_wait_values else math.nan
    p50_queue_wait = calculate_percentile(queue_wait_values, 50)
    p95_queue_wait = calculate_percentile(queue_wait_values, 95)
    p99_queue_wait = calculate_percentile(queue_wait_values, 99)

    avg_processing = sum(processing_values) / len(processing_values) if processing_values else math.nan
    p50_processing = calculate_percentile(processing_values, 50)
    p95_processing = calculate_percentile(processing_values, 95)
    p99_processing = calculate_percentile(processing_values, 99)

    avg_scheduler_total = sum(scheduler_total_values) / len(scheduler_total_values) if scheduler_total_values else math.nan
    p50_scheduler_total = calculate_percentile(scheduler_total_values, 50)
    p95_scheduler_total = calculate_percentile(scheduler_total_values, 95)
    p99_scheduler_total = calculate_percentile(scheduler_total_values, 99)

    summary_stats = {
        "total_requests": total_requests,
        "successful_requests": successes,
        "failed_requests": errors,
        "error_rate": error_rate,
        "slo_attainment_rate": slo_attainment_rate,
        "avg_ttft_ms": avg_ttft,
        "p50_ttft_ms": p50_ttft,
        "p95_ttft_ms": p95_ttft,
        "p99_ttft_ms": p99_ttft,
        "avg_tpot_ms": avg_tpot,
        "p50_tpot_ms": p50_tpot,
        "p95_tpot_ms": p95_tpot,
        "p99_tpot_ms": p99_tpot,
        "avg_latency_ms": avg_latency,
        "p50_latency_ms": p50_latency,
        "p95_latency_ms": p95_latency,
        "p99_latency_ms": p99_latency,
        "avg_queue_wait_ms": avg_queue_wait,
        "p50_queue_wait_ms": p50_queue_wait,
        "p95_queue_wait_ms": p95_queue_wait,
        "p99_queue_wait_ms": p99_queue_wait,
        "avg_processing_ms": avg_processing,
        "p50_processing_ms": p50_processing,
        "p95_processing_ms": p95_processing,
        "p99_processing_ms": p99_processing,
        "avg_scheduler_total_ms": avg_scheduler_total,
        "p50_scheduler_total_ms": p50_scheduler_total,
        "p95_scheduler_total_ms": p95_scheduler_total,
        "p99_scheduler_total_ms": p99_scheduler_total,
    }

    return summary_stats, detail_records, missing_logs


def write_summary_csv(path: Path, summary_stats: Dict[str, object]) -> None:
    """Write a compact summary CSV with aggregated metrics."""
    path.parent.mkdir(parents=True, exist_ok=True)

    def fmt(value: object) -> str:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return "N/A"
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value)

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "value", "unit"])

        # Request counts
        writer.writerow(["total_requests", summary_stats["total_requests"], "count"])
        writer.writerow(["successful_requests", summary_stats["successful_requests"], "count"])
        writer.writerow(["failed_requests", summary_stats["failed_requests"], "count"])
        writer.writerow(["error_rate", fmt(summary_stats["error_rate"]), "%"])
        writer.writerow(["slo_attainment_rate", fmt(summary_stats["slo_attainment_rate"]), "%"])

        # TTFT metrics
        writer.writerow(["avg_ttft", fmt(summary_stats["avg_ttft_ms"]), "ms"])
        writer.writerow(["p50_ttft", fmt(summary_stats["p50_ttft_ms"]), "ms"])
        writer.writerow(["p95_ttft", fmt(summary_stats["p95_ttft_ms"]), "ms"])
        writer.writerow(["p99_ttft", fmt(summary_stats["p99_ttft_ms"]), "ms"])

        # TPOT metrics
        writer.writerow(["avg_tpot", fmt(summary_stats["avg_tpot_ms"]), "ms/token"])
        writer.writerow(["p50_tpot", fmt(summary_stats["p50_tpot_ms"]), "ms/token"])
        writer.writerow(["p95_tpot", fmt(summary_stats["p95_tpot_ms"]), "ms/token"])
        writer.writerow(["p99_tpot", fmt(summary_stats["p99_tpot_ms"]), "ms/token"])

        # Total latency metrics
        writer.writerow(["avg_total_latency", fmt(summary_stats["avg_latency_ms"]), "ms"])
        writer.writerow(["p50_total_latency", fmt(summary_stats["p50_latency_ms"]), "ms"])
        writer.writerow(["p95_total_latency", fmt(summary_stats["p95_latency_ms"]), "ms"])
        writer.writerow(["p99_total_latency", fmt(summary_stats["p99_latency_ms"]), "ms"])

        # Queue wait metrics
        writer.writerow(["avg_queue_wait", fmt(summary_stats["avg_queue_wait_ms"]), "ms"])
        writer.writerow(["p50_queue_wait", fmt(summary_stats["p50_queue_wait_ms"]), "ms"])
        writer.writerow(["p95_queue_wait", fmt(summary_stats["p95_queue_wait_ms"]), "ms"])
        writer.writerow(["p99_queue_wait", fmt(summary_stats["p99_queue_wait_ms"]), "ms"])

        # Processing metrics (scheduled to complete)
        writer.writerow(["avg_processing", fmt(summary_stats["avg_processing_ms"]), "ms"])
        writer.writerow(["p50_processing", fmt(summary_stats["p50_processing_ms"]), "ms"])
        writer.writerow(["p95_processing", fmt(summary_stats["p95_processing_ms"]), "ms"])
        writer.writerow(["p99_processing", fmt(summary_stats["p99_processing_ms"]), "ms"])

        # Scheduler total metrics (enqueue to complete)
        writer.writerow(["avg_scheduler_total", fmt(summary_stats["avg_scheduler_total_ms"]), "ms"])
        writer.writerow(["p50_scheduler_total", fmt(summary_stats["p50_scheduler_total_ms"]), "ms"])
        writer.writerow(["p95_scheduler_total", fmt(summary_stats["p95_scheduler_total_ms"]), "ms"])
        writer.writerow(["p99_scheduler_total", fmt(summary_stats["p99_scheduler_total_ms"]), "ms"])


def write_detailed_csv(path: Path, detail_records: List[Dict[str, object]]) -> None:
    """Write a detailed CSV with individual request data."""
    path.parent.mkdir(parents=True, exist_ok=True)

    headers = [
        "log_id",
        "request_id",
        "server_request_id",
        "scenario_name",
        "arrival_offset_ms",
        "mode",
        "priority",
        "priority_when_scheduled",
        "http_status",
        "client_duration_ms",
        "request_body_json",
        "provider_name",
        "model_name",
        "cold_start",
        "load_duration_ms",
        "result_status",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "total_tokens_per_second",
        "completion_tokens_per_second",
        "ttft_ms",
        "tpot_ms",
        "tokens",
        "total_latency_ms",
        "queue_depth_at_arrival",
        "utilization_at_arrival",
        "queue_depth_at_schedule",
        "queue_wait_ms",
        "processing_ms",
        "scheduler_total_ms",
        "request_ts_utc",
        "ttft_ts_utc",
        "response_ts_utc",
        "available_vram_mb",
        "azure_rate_remaining_requests",
        "azure_rate_remaining_tokens",
        "response_body_json",
        "response_text",
        "error",
    ]

    def fmt(value: object) -> str:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return ""
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value)

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for rec in detail_records:
            writer.writerow([
                fmt(rec.get("log_id")),
                rec.get("request_id", ""),
                rec.get("server_request_id", ""),
                rec.get("scenario_name", ""),
                fmt(rec.get("arrival_offset_ms")),
                rec.get("mode", ""),
                rec.get("priority", ""),
                rec.get("priority_when_scheduled", ""),
                fmt(rec.get("http_status")),
                fmt(rec.get("client_duration_ms")),
                rec.get("request_body_json", ""),
                rec.get("provider_name", ""),
                rec.get("model_name", ""),
                fmt(rec.get("cold_start")),
                fmt(rec.get("load_duration_ms")),
                rec.get("result_status", ""),
                fmt(rec.get("prompt_tokens")),
                fmt(rec.get("completion_tokens")),
                fmt(rec.get("total_tokens")),
                fmt(rec.get("total_tokens_per_second")),
                fmt(rec.get("completion_tokens_per_second")),
                fmt(rec.get("ttft_ms")),
                fmt(rec.get("tpot_ms")),
                fmt(rec.get("tokens")),
                fmt(rec.get("total_latency_ms")),
                fmt(rec.get("queue_depth_at_arrival")),
                fmt(rec.get("utilization_at_arrival")),
                fmt(rec.get("queue_depth_at_schedule")),
                fmt(rec.get("queue_wait_ms")),
                fmt(rec.get("processing_ms")),
                fmt(rec.get("scheduler_total_ms")),
                rec.get("request_ts_utc", ""),
                rec.get("ttft_ts_utc", ""),
                rec.get("response_ts_utc", ""),
                fmt(rec.get("available_vram_mb")),
                fmt(rec.get("azure_rate_remaining_requests")),
                fmt(rec.get("azure_rate_remaining_tokens")),
                rec.get("response_body_json", ""),
                rec.get("response_text", ""),
                rec.get("error", ""),
            ])


def build_request_response_records(detail_records: Sequence[Dict[str, object]]) -> list[dict]:
    records: list[dict] = []
    for rec in detail_records:
        records.append(
            {
                "scenario_name": rec.get("scenario_name"),
                "request_id": rec.get("request_id"),
                "server_request_id": rec.get("server_request_id"),
                "log_id": rec.get("log_id"),
                "arrival_offset_ms": rec.get("arrival_offset_ms"),
                "mode": rec.get("mode"),
                "priority": rec.get("priority"),
                "priority_when_scheduled": rec.get("priority_when_scheduled"),
                "http_status": rec.get("http_status"),
                "provider_name": rec.get("provider_name"),
                "model_name": rec.get("model_name"),
                "request_ts_utc": rec.get("request_ts_utc"),
                "ttft_ts_utc": rec.get("ttft_ts_utc"),
                "response_ts_utc": rec.get("response_ts_utc"),
                "client_duration_ms": rec.get("client_duration_ms"),
                "ttft_ms": rec.get("ttft_ms"),
                "total_latency_ms": rec.get("total_latency_ms"),
                "queue_wait_ms": rec.get("queue_wait_ms"),
                "processing_ms": rec.get("processing_ms"),
                "scheduler_total_ms": rec.get("scheduler_total_ms"),
                "prompt_tokens": rec.get("prompt_tokens"),
                "completion_tokens": rec.get("completion_tokens"),
                "total_tokens": rec.get("total_tokens"),
                "cold_start": rec.get("cold_start"),
                "load_duration_ms": rec.get("load_duration_ms"),
                "error": rec.get("error"),
                "request_payload": rec.get("_request_payload"),
                "response_payload": rec.get("_response_payload"),
            }
        )
    return records


def build_per_model_summary_rows(detail_records: Sequence[Dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[Dict[str, object]]] = {}
    for rec in detail_records:
        model_name = str(rec.get("model_name") or "unknown")
        grouped.setdefault(model_name, []).append(rec)

    rows: list[dict[str, object]] = []
    for model_name, records in sorted(grouped.items()):
        success_count = sum(1 for rec in records if isinstance(rec.get("http_status"), int) and rec["http_status"] < 400)

        def values_for(field: str) -> list[float]:
            values = [float(rec[field]) for rec in records if isinstance(rec.get(field), (int, float))]
            return values

        ttft_values = values_for("ttft_ms")
        latency_values = values_for("total_latency_ms")
        queue_values = values_for("queue_wait_ms")
        processing_values = values_for("processing_ms")
        rows.append(
            {
                "model_name": model_name,
                "request_count": len(records),
                "successful_requests": success_count,
                "success_rate_pct": (success_count / len(records) * 100.0) if records else math.nan,
                "p50_ttft_ms": calculate_percentile(ttft_values, 50),
                "p95_ttft_ms": calculate_percentile(ttft_values, 95),
                "p99_ttft_ms": calculate_percentile(ttft_values, 99),
                "p50_latency_ms": calculate_percentile(latency_values, 50),
                "p95_latency_ms": calculate_percentile(latency_values, 95),
                "p99_latency_ms": calculate_percentile(latency_values, 99),
                "p50_queue_wait_ms": calculate_percentile(queue_values, 50),
                "p95_queue_wait_ms": calculate_percentile(queue_values, 95),
                "p99_queue_wait_ms": calculate_percentile(queue_values, 99),
                "p50_processing_ms": calculate_percentile(processing_values, 50),
                "p95_processing_ms": calculate_percentile(processing_values, 95),
                "p99_processing_ms": calculate_percentile(processing_values, 99),
            }
        )
    return rows


def write_per_model_summary_csv(path: Path, rows: Sequence[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "model_name",
        "request_count",
        "successful_requests",
        "success_rate_pct",
        "p50_ttft_ms",
        "p95_ttft_ms",
        "p99_ttft_ms",
        "p50_latency_ms",
        "p95_latency_ms",
        "p99_latency_ms",
        "p50_queue_wait_ms",
        "p95_queue_wait_ms",
        "p99_queue_wait_ms",
        "p50_processing_ms",
        "p95_processing_ms",
        "p99_processing_ms",
    ]

    def fmt(value: object) -> str:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return ""
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value)

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([fmt(row.get(header)) for header in headers])


def write_json(path: Path, payload: Optional[dict]) -> None:
    if payload is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: Sequence[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def generate_visualizations(path: Path, detail_records: Sequence[Dict[str, object]]) -> None:
    generate_overview_charts(path, detail_records)


async def run_workload(
    workload: Sequence[WorkloadEntry],
    logos_key: str,
    base_url: str,
    request_timeout_s: float,
) -> tuple[List[RequestResult], list[dict]]:
    async def report_progress(
        start_monotonic: float,
        completed_counter: dict[str, int],
        stop_event: asyncio.Event,
    ) -> None:
        loop = asyncio.get_event_loop()
        total = len(workload)
        while not stop_event.is_set():
            elapsed_s = loop.time() - start_monotonic
            due = sum(1 for entry in workload if (entry.arrival_offset / 1000.0) <= elapsed_s)
            print(
                f"[progress] elapsed={elapsed_s:.1f}s due={due}/{total} completed={completed_counter['count']}/{total}",
                flush=True,
            )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                continue

    async with httpx.AsyncClient(timeout=request_timeout_s) as client:
        start_monotonic = asyncio.get_event_loop().time()
        stop_event = asyncio.Event()
        completed_counter = {"count": 0}
        runtime_task = asyncio.create_task(
            collect_runtime_samples(
                client,
                base_url,
                logos_key,
                stop_event,
                interval_s=1.0,
            )
        )
        progress_task = asyncio.create_task(
            report_progress(
                start_monotonic,
                completed_counter,
                stop_event,
            )
        )
        tasks = [
            asyncio.create_task(dispatch_request(client, base_url, logos_key, entry, start_monotonic))
            for entry in workload
        ]
        results: List[RequestResult] = []
        try:
            for task in asyncio.as_completed(tasks):
                result = await task
                results.append(result)
                completed_counter["count"] += 1
                if completed_counter["count"] == len(workload):
                    print(
                        f"[progress] elapsed={asyncio.get_event_loop().time() - start_monotonic:.1f}s "
                        f"due={len(workload)}/{len(workload)} completed={len(workload)}/{len(workload)}",
                        flush=True,
                    )
        finally:
            stop_event.set()
            await asyncio.gather(progress_task, return_exceptions=True)
        runtime_samples = await runtime_task
        return results, runtime_samples


def wait_for_log_records(
    process_id: int,
    start_log_id: int,
    expected_count: int,
    timeout: float = 30.0,
    poll_interval: float = 1.0,
) -> List[LogRecord]:
    deadline = time.monotonic() + timeout
    logs: List[LogRecord] = []
    while True:
        logs = fetch_log_records(process_id, start_log_id)
        if len(logs) >= expected_count or time.monotonic() >= deadline:
            return logs
        time.sleep(poll_interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay workload against Logos API.")
    parser.add_argument("--logos-key", required=True, help="Logos API key used for authentication.")
    parser.add_argument("--workload", type=Path, required=True, help="Path to workload CSV.")
    parser.add_argument("--api-base", default="http://localhost:8080", help="Base URL for the Logos API.")
    parser.add_argument("--output", type=Path, help="Destination CSV file.")
    parser.add_argument(
        "--run-timestamp",
        help="Optional precomputed local timestamp in YYYYMMDD_HHMMSS format, typically passed by the wrapper.",
    )
    parser.add_argument("--latency-slo-ms", type=float, default=10_000.0, help="Latency SLO threshold in milliseconds.")
    parser.add_argument(
        "--request-timeout-s",
        type=float,
        default=1200.0,
        help="Per-request timeout in seconds.",
    )
    args = parser.parse_args()

    workload = parse_workload(args.workload)
    scenario_manifest = load_workload_scenario_manifest(args.workload, workload)
    scenario_name = str(scenario_manifest.get("scenario_name") or args.workload.stem)
    local_mode = is_local_api_base(args.api_base)
    process_id = None
    original_log = None
    restore_log = "BILLING"
    start_log_id = 0
    if local_mode:
        process_id, original_log = fetch_process_metadata(args.logos_key)
        restore_log = original_log if original_log else "BILLING"
        if original_log != "FULL":
            set_log_level(process_id, "FULL")
        start_log_id = current_log_max(process_id)

    run_started_at = datetime.now(timezone.utc)
    run_timestamp = args.run_timestamp or datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    output_layout = resolve_output_layout(args.output, args.workload, run_timestamp)
    print(f"Executing {len(workload)} requests via {args.api_base} (/v1/...)")
    try:
        results, runtime_samples = asyncio.run(run_workload(workload, args.logos_key, args.api_base, args.request_timeout_s))
        if local_mode:
            logs = wait_for_log_records(
                process_id,
                start_log_id,
                expected_count=len(results),
                timeout=30.0,
                poll_interval=1.0,
            )
        else:
            server_request_ids = [result.server_request_id for result in results if result.server_request_id]
            logs = wait_for_request_logs_via_api(
                args.api_base,
                args.logos_key,
                server_request_ids,
                timeout=30.0,
                poll_interval=1.0,
            )
        run_finished_at = datetime.now(timezone.utc)
        runtime_artifacts = fetch_runtime_artifacts(
            args.api_base,
            args.logos_key,
            start_ts=run_started_at,
            end_ts=run_finished_at,
            runtime_samples=runtime_samples,
        )
        summary_stats, detail_records, missing_logs = build_rows(
            results,
            logs,
            args.latency_slo_ms,
            scenario_name=scenario_name,
        )
        request_response_records = build_request_response_records(detail_records)
        per_model_summary_rows = build_per_model_summary_rows(detail_records)
        latency_series = prepare_distribution_series(
            metric_name="Total Latency",
            values=[float(rec["total_latency_ms"]) for rec in detail_records if isinstance(rec.get("total_latency_ms"), (int, float))],
        )
        ttft_series = prepare_distribution_series(
            metric_name="TTFT",
            values=[float(rec["ttft_ms"]) for rec in detail_records if isinstance(rec.get("ttft_ms"), (int, float))],
        )

        write_summary_csv(output_layout.summary_path, summary_stats)
        write_detailed_csv(output_layout.detailed_path, detail_records)
        generate_visualizations(output_layout.detailed_path, detail_records)
        write_json(output_layout.scenario_manifest_path, scenario_manifest)
        write_jsonl(output_layout.request_response_path, request_response_records)
        write_per_model_summary_csv(output_layout.per_model_summary_path, per_model_summary_rows)
        write_distribution_csv(output_layout.latency_distribution_csv_path, latency_series)
        write_distribution_csv(output_layout.ttft_distribution_csv_path, ttft_series)
        latency_chart_meta = render_distribution_chart(
            path_without_suffix=output_layout.latency_distribution_chart_path,
            series=latency_series,
            scenario_name=scenario_name,
            color="#7BA7D7",
            curve_color="#204B77",
        )
        ttft_chart_meta = render_distribution_chart(
            path_without_suffix=output_layout.ttft_distribution_chart_path,
            series=ttft_series,
            scenario_name=scenario_name,
            color="#8CC8A3",
            curve_color="#1E6A52",
        )
        write_jsonl(output_layout.runtime_samples_path, runtime_artifacts.runtime_samples)
        write_json(output_layout.provider_vram_path, runtime_artifacts.provider_vram)
        write_json(output_layout.request_log_stats_path, runtime_artifacts.request_log_stats)
        write_json(
            output_layout.run_meta_path,
            {
                "workload": str(args.workload),
                "api_base": args.api_base,
                "request_timeout_s": args.request_timeout_s,
                "request_count": len(results),
                "scenario_name": scenario_name,
                "layout": scenario_manifest.get("layout"),
                "seed": scenario_manifest.get("seed"),
                "model_counts": scenario_manifest.get("model_counts"),
                "experiment_name": output_layout.experiment_name,
                "output_dir": str(output_layout.run_dir),
                "run_started_at": isoformat_utc(run_started_at),
                "run_finished_at": isoformat_utc(run_finished_at),
                "output_summary_csv": str(output_layout.summary_path),
                "output_detailed_csv": str(output_layout.detailed_path),
                "output_scenario_manifest_json": str(output_layout.scenario_manifest_path),
                "output_request_response_jsonl": str(output_layout.request_response_path),
                "output_per_model_summary_csv": str(output_layout.per_model_summary_path),
                "output_latency_distribution_csv": str(output_layout.latency_distribution_csv_path),
                "output_ttft_distribution_csv": str(output_layout.ttft_distribution_csv_path),
                "output_latency_distribution_png": latency_chart_meta["png_path"],
                "output_latency_distribution_svg": latency_chart_meta["svg_path"],
                "output_ttft_distribution_png": ttft_chart_meta["png_path"],
                "output_ttft_distribution_svg": ttft_chart_meta["svg_path"],
                "output_runtime_samples_jsonl": str(output_layout.runtime_samples_path),
                "output_provider_vram_json": str(output_layout.provider_vram_path),
                "output_request_log_stats_json": str(output_layout.request_log_stats_path),
            },
        )

        if missing_logs:
            if isinstance(logs, dict):
                print(
                    f"Warning: matched {len(results) - missing_logs}/{len(results)} requests to log entries by request_id. "
                    "Some rows are marked with 'log entry missing'."
                )
            else:
                print(
                    f"Warning: expected {len(results)} new log entries but only found {len(logs)}. "
                    "Some rows are marked with 'log entry missing'."
                )
        print(f"Completed run. Summary: {len(results)} requests")
        print(f"  Result folder: {output_layout.run_dir}")
        print(f"  Summary metrics: {output_layout.summary_path}")
        print(f"  Detailed results: {output_layout.detailed_path}")
        print(f"  Scenario manifest: {output_layout.scenario_manifest_path}")
        print(f"  Request/response log: {output_layout.request_response_path}")
        print(f"  Per-model summary: {output_layout.per_model_summary_path}")
        print(f"  Latency distribution: {output_layout.latency_distribution_csv_path}")
        print(f"  TTFT distribution: {output_layout.ttft_distribution_csv_path}")
        print(f"  Runtime samples: {output_layout.runtime_samples_path}")
        print(f"  Provider VRAM: {output_layout.provider_vram_path}")
        print(f"  Request log stats: {output_layout.request_log_stats_path}")
        print(f"  Run metadata: {output_layout.run_meta_path}")
    finally:
        if local_mode and original_log != "FULL":
            set_log_level(process_id, restore_log)
        print("Restored process log level.")


if __name__ == "__main__":
    main()

"""
Replay a scheduling workload CSV (see tests/performance/workloads/README.md) against a running Logos API
instance and aggregate per-request metrics. Generates a detailed CSV plus latency charts.

RECOMMENDED USAGE (shell script wrapper):

    ./tests/performance/test_scheduling_performance.sh \
        --logos-key YourLogosApiKey \
        --workload tests/performance/workloads/sample_workload_mixed.csv \
        --latency-slo-ms 10000

    This script handles Docker container startup, waits for API readiness,
    and persists results to your local repo via volume mounts.

DIRECT PYTHON USAGE (advanced - requires manual Docker setup):

    docker compose exec logos-server poetry run python tests/performance/run_api_workload.py \
        --logos-key YourLogosApiKey \
        --workload tests/performance/workloads/sample_workload_mixed.csv \
        --api-base http://localhost:8080 \
        --latency-slo-ms 10000 \
        --output tests/performance/results/api_benchmark.csv

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
from datetime import datetime, timezone
from pathlib import Path
from string import Template
from typing import Dict, List, Optional, Sequence

import httpx
from sqlalchemy import text

from logos.dbutils.dbmanager import DBManager

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


@dataclass(slots=True)
class WorkloadEntry:
    request_id: str
    arrival_offset: float
    mode: str
    priority: str
    body_json: str

    def render_payload(self) -> Dict[str, object]:
        try:
            payload = json.loads(self.body_json)
            # Add mode and priority to the payload for tracking
            payload["mode"] = self.mode
            payload["priority"] = self.map_priority_to_int()
            return payload
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"{self.request_id}: body_json column is not valid JSON.") from exc

    def map_priority_to_int(self) -> int:
        """Map priority string to integer value."""
        priority_map = {
            "low": 1,
            "mid": 5,
            "high": 10,
        }
        return priority_map.get(self.priority.lower(), 5)  # Default to mid (5)

@dataclass(slots=True)
class RequestResult:
    entry: WorkloadEntry
    status_code: int
    response_body: Optional[dict]
    error: Optional[str]
    duration_ms: float


@dataclass(slots=True)
class LogRecord:
    log_id: int
    request_ts: datetime
    forward_ts: Optional[datetime]
    ttft_ts: Optional[datetime]
    response_ts: Optional[datetime]
    provider_id: Optional[int]
    provider_name: Optional[str]
    model_id: Optional[int]
    model_name: Optional[str]
    response_payload: Optional[dict]

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
        response = await client.request(
            "POST",
            url,
            json=payload,
            headers=headers,
        )
        duration_ms = (time.perf_counter() - start) * 1000
        body: Optional[dict]
        try:
            body = response.json()
        except json.JSONDecodeError:
            body = {"text": response.text}
        error = None if response.status_code < 400 else body
        return RequestResult(
            entry=entry,
            status_code=response.status_code,
            response_body=body,
            error=None if error is None else json.dumps(error)[:500],
            duration_ms=duration_ms,
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


def fetch_log_records(process_id: int, start_log_id: int) -> List[LogRecord]:
    with DBManager() as db:
        rows = db.session.execute(
            text(
                """
                SELECT
                    le.id,
                    le.timestamp_request,
                    le.timestamp_forwarding,
                    le.time_at_first_token,
                    le.timestamp_response,
                    le.provider_id,
                    providers.name AS provider_name,
                    le.model_id,
                    models.name AS model_name,
                    le.response_payload
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
                request_ts=row.timestamp_request,
                forward_ts=row.timestamp_forwarding,
                ttft_ts=row.time_at_first_token,
                response_ts=row.timestamp_response,
                provider_id=row.provider_id,
                provider_name=row.provider_name,
                model_id=row.model_id,
                model_name=row.model_name,
                response_payload=payload,
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
    for key in ("output_tokens", "tokens_generated", "num_tokens"):
        value = payload.get(key)
        if isinstance(value, int):
            return value

    return None


def calculate_percentile(values: List[float], percentile: float) -> float:
    """Calculate the given percentile of a list of values."""
    if not values:
        return math.nan
    sorted_values = sorted(values)
    index = (len(sorted_values) - 1) * (percentile / 100.0)
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return sorted_values[lower]
    return sorted_values[lower] * (upper - index) + sorted_values[upper] * (index - lower)


def build_rows(
    results: Sequence[RequestResult],
    logs: Sequence[LogRecord],
    latency_slo_ms: float,
) -> tuple[Dict[str, object], List[Dict[str, object]], int]:
    detail_records: List[Dict[str, object]] = []
    ttft_values: List[float] = []
    tpot_values: List[float] = []
    latency_values: List[float] = []
    successes = 0

    missing_logs = max(0, len(results) - len(logs))
    padded_logs: List[Optional[LogRecord]] = list(logs[: len(results)]) + [None] * missing_logs

    for result, log in zip(results, padded_logs):
        ttft: Optional[float] = None
        total_latency: Optional[float] = None
        provider_id: Optional[int] = None
        provider_name: Optional[str] = None
        model_id: Optional[int] = None
        model_name: Optional[str] = None
        response_text: Optional[str] = None
        log_id: Optional[int] = None
        tokens: Optional[int] = None
        tpot: Optional[float] = None

        if log is not None:
            ttft = log.ttft_ms
            total_latency = log.total_latency_ms
            provider_id = log.provider_id
            provider_name = log.provider_name
            model_id = log.model_id
            model_name = log.model_name
            response_text = extract_response_text(log.response_payload)
            tokens = extract_token_count(log.response_payload)
            log_id = log.log_id

            # Calculate TPOT (Time Per Output Token)
            if ttft is not None and total_latency is not None and tokens is not None and tokens > 1:
                tpot = (total_latency - ttft) / (tokens - 1)

            if ttft is not None:
                ttft_values.append(ttft)
            if tpot is not None:
                tpot_values.append(tpot)
            if total_latency is not None:
                latency_values.append(total_latency)

        if result.status_code and result.status_code < 400:
            successes += 1

        error_text = result.error
        if log is None:
            note = "log entry missing"
            error_text = f"{result.error} | {note}" if result.error else note

        record = {
            "log_id": log_id,
            "request_id": result.entry.request_id,
            "mode": result.entry.mode,
            "priority": result.entry.priority,
            "http_status": result.status_code,
            "client_duration_ms": result.duration_ms,
            "provider_id": provider_id,
            "provider_name": provider_name,
            "model_id": model_id,
            "model_name": model_name,
            "ttft_ms": ttft,
            "tpot_ms": tpot,
            "tokens": tokens,
            "total_latency_ms": total_latency,
            "response_text": response_text,
            "error": error_text,
        }
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


def write_detailed_csv(path: Path, detail_records: List[Dict[str, object]]) -> None:
    """Write a detailed CSV with individual request data."""
    path.parent.mkdir(parents=True, exist_ok=True)

    headers = [
        "log_id",
        "request_id",
        "mode",
        "priority",
        "http_status",
        "client_duration_ms",
        "provider_name",
        "model_name",
        "ttft_ms",
        "tpot_ms",
        "tokens",
        "total_latency_ms",
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
                rec.get("mode", ""),
                rec.get("priority", ""),
                fmt(rec.get("http_status")),
                fmt(rec.get("client_duration_ms")),
                rec.get("provider_name", ""),
                rec.get("model_name", ""),
                fmt(rec.get("ttft_ms")),
                fmt(rec.get("tpot_ms")),
                fmt(rec.get("tokens")),
                fmt(rec.get("total_latency_ms")),
                rec.get("response_text", ""),
                rec.get("error", ""),
            ])


def generate_visualizations(path: Path, detail_records: Sequence[Dict[str, object]]) -> None:
    successful = [
        rec for rec in detail_records
        if rec["response_text"] and isinstance(rec["total_latency_ms"], (int, float)) and isinstance(rec["client_duration_ms"], (int, float))
    ]
    if not successful:
        return

    request_labels = [rec["request_id"] for rec in successful]
    total_latencies = [rec["total_latency_ms"] for rec in successful]
    ttfts = [rec["ttft_ms"] if isinstance(rec["ttft_ms"], (int, float)) else 0.0 for rec in successful]
    client_durations = [rec["client_duration_ms"] for rec in successful]

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(request_labels, total_latencies, label="Total latency (ms)", color="#4C72B0")
    ax.bar(request_labels, ttfts, label="TTFT (ms)", color="#55A868")
    ax.set_xlabel("Request ID")
    ax.set_ylabel("Milliseconds")
    ax.set_title("Latency Breakdown (Successful Requests)")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path.with_suffix(".png"))
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(request_labels, client_durations, marker="o", linewidth=2, label="Client duration (ms)", color="#C44E52")
    ax.set_xlabel("Request ID")
    ax.set_ylabel("Milliseconds")
    ax.set_title("Client Duration per Successful Request")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path.with_name(path.stem + "_client_duration.png"))
    plt.close(fig)


async def run_workload(
    workload: Sequence[WorkloadEntry],
    logos_key: str,
    base_url: str,
) -> List[RequestResult]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        start_monotonic = asyncio.get_event_loop().time()
        tasks = [
            asyncio.create_task(dispatch_request(client, base_url, logos_key, entry, start_monotonic))
            for entry in workload
        ]
        return await asyncio.gather(*tasks)


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
    parser.add_argument("--output", type=Path, default=Path("api_benchmark.csv"), help="Destination CSV file.")
    parser.add_argument("--latency-slo-ms", type=float, default=10_000.0, help="Latency SLO threshold in milliseconds.")
    args = parser.parse_args()

    workload = parse_workload(args.workload)
    process_id, original_log = fetch_process_metadata(args.logos_key)
    restore_log = original_log if original_log else "BILLING"
    if original_log != "FULL":
        set_log_level(process_id, "FULL")
    start_log_id = current_log_max(process_id)

    print(f"Executing {len(workload)} requests via {args.api_base} (/v1/...)")
    try:
        results = asyncio.run(run_workload(workload, args.logos_key, args.api_base))
        logs = wait_for_log_records(
            process_id,
            start_log_id,
            expected_count=len(results),
            timeout=30.0,
            poll_interval=1.0,
        )
        summary_stats, detail_records, missing_logs = build_rows(results, logs, args.latency_slo_ms)

        # Generate output file paths
        output_base = args.output.stem
        output_dir = args.output.parent
        summary_path = output_dir / f"{output_base}_summary.csv"
        detailed_path = output_dir / f"{output_base}_detailed.csv"

        # Write both CSV files
        write_summary_csv(summary_path, summary_stats)
        write_detailed_csv(detailed_path, detail_records)
        generate_visualizations(detailed_path, detail_records)

        if missing_logs:
            print(
                f"Warning: expected {len(results)} new log entries but only found {len(logs)}. "
                "Some rows are marked with 'log entry missing'."
            )
        print(f"Completed run. Summary: {len(results)} requests")
        print(f"  Summary metrics: {summary_path}")
        print(f"  Detailed results: {detailed_path}")
    finally:
        if original_log != "FULL":
            set_log_level(process_id, restore_log)
        print("Restored process log level.")


if __name__ == "__main__":
    main()

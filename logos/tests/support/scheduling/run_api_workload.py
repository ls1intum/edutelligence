"""
Replay a scheduling workload CSV (see tests/fixtures/scheduling/README.md) against a running Logos API
instance and aggregate per-request metrics. Generates a detailed CSV plus latency charts.

Usage (inside the logos-server container):

    poetry run python logos/tests/support/scheduling/run_api_workload.py \
        --logos-key YourLogosApiKey \
        --workload logos/tests/fixtures/scheduling/sample_workload.csv \
        --api-base http://localhost:8080 \
        --latency-slo-ms 10000 \
        --output logos/tests/results/scheduling/api_benchmark.csv
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
    prompt: str
    mode: str
    body_json: Optional[str]
    body_template: Optional[str]

    def render_payload(self) -> Dict[str, object]:
        if self.body_json:
            try:
                return json.loads(self.body_json)
            except (json.JSONDecodeError, TypeError) as exc:
                raise ValueError(f"{self.request_id}: body_json column is not valid JSON.") from exc
        if self.body_template:
            try:
                rendered = Template(self.body_template).substitute(prompt=self.prompt)
            except KeyError as exc:
                raise ValueError(f"{self.request_id}: body_template is missing placeholder {exc!s}.") from exc
            except Exception as exc:
                raise ValueError(f"{self.request_id}: failed to render body_template.") from exc
            try:
                return json.loads(rendered)
            except (json.JSONDecodeError, TypeError) as exc:
                raise ValueError(f"{self.request_id}: rendered body_template is not valid JSON.") from exc
        return {
            "messages": [
                {"role": "user", "content": self.prompt},
            ],
            "mode": self.mode,
        }

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
    wait = entry.arrival_offset - (asyncio.get_event_loop().time() - start_monotonic)
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
        required = {"arrival_offset", "prompt", "mode"}
        missing = required - set(reader.fieldnames)
        if missing:
            raise ValueError(f"Workload file is missing required columns: {', '.join(sorted(missing))}")
        for idx, row in enumerate(reader, start=1):
            request_id = row.get("request_id") or f"req-{idx}"
            try:
                offset = float(row["arrival_offset"])
            except ValueError as exc:
                raise ValueError(f"Invalid arrival_offset for row {idx}: {row['arrival_offset']}") from exc
            entries.append(
                WorkloadEntry(
                    request_id=request_id,
                    arrival_offset=offset,
                    prompt=row["prompt"],
                    mode=row["mode"],
                    body_json=row.get("body_json"),
                    body_template=row.get("body_template"),
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


def build_rows(
    results: Sequence[RequestResult],
    logs: Sequence[LogRecord],
    latency_slo_ms: float,
) -> tuple[List[List[object]], List[List[object]], int, List[Dict[str, object]]]:
    detail_rows: List[List[object]] = []
    detail_records: List[Dict[str, object]] = []
    ttft_values: List[float] = []
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

        if log is not None:
            ttft = log.ttft_ms
            total_latency = log.total_latency_ms
            provider_id = log.provider_id
            provider_name = log.provider_name
            model_id = log.model_id
            model_name = log.model_name
            response_text = extract_response_text(log.response_payload)
            log_id = log.log_id
            if ttft is not None:
                ttft_values.append(ttft)
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
            "prompt": result.entry.prompt,
            "mode": result.entry.mode,
            "http_status": result.status_code,
            "client_duration_ms": result.duration_ms,
            "provider_id": provider_id,
            "provider_name": provider_name,
            "model_id": model_id,
            "model_name": model_name,
            "ttft_ms": ttft,
            "total_latency_ms": total_latency,
            "response_text": response_text,
            "error": error_text,
        }
        detail_records.append(record)

        detail_rows.append([
            "request",
            log_id,
            result.entry.request_id,
            result.entry.prompt.replace("\n", " "),
            result.entry.mode,
            result.status_code,
            f"{result.duration_ms:.2f}",
            provider_id,
            provider_name,
            model_id,
            model_name,
            "" if ttft is None else f"{ttft:.2f}",
            "" if total_latency is None else f"{total_latency:.2f}",
            response_text,
            error_text,
            "",
            "",
            "",
            "",
            "",
            "",
        ])

    total_requests = len(results)
    errors = total_requests - successes
    slo_hits = sum(1 for latency in latency_values if latency <= latency_slo_ms)
    avg_ttft = sum(ttft_values) / len(ttft_values) if ttft_values else math.nan
    avg_latency = sum(latency_values) / len(latency_values) if latency_values else math.nan

    successful_records = [rec for rec in detail_records if rec["response_text"]]
    successful_ttft = [rec["ttft_ms"] for rec in successful_records if isinstance(rec["ttft_ms"], (int, float))]
    successful_latency = [rec["total_latency_ms"] for rec in successful_records if isinstance(rec["total_latency_ms"], (int, float))]

    def fmt(value: Optional[float]) -> str:
        return "" if value is None or math.isnan(value) else f"{value:.2f}"

    successful_successes = sum(1 for rec in successful_records if rec["http_status"] and rec["http_status"] < 400)
    successful_errors = len(successful_records) - successful_successes

    summary_rows = [[
        "summary",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        total_requests,
        successes,
        errors,
        fmt(avg_ttft),
        fmt(avg_latency),
        fmt(slo_hits / total_requests if total_requests else math.nan),
    ], [
        "summary_successful",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        len(successful_records),
        successful_successes,
        successful_errors,
        fmt(sum(successful_ttft) / len(successful_ttft) if successful_ttft else math.nan),
        fmt(sum(successful_latency) / len(successful_latency) if successful_latency else math.nan),
        fmt(sum(1 for latency in successful_latency if latency <= latency_slo_ms) / len(successful_latency) if successful_latency else math.nan),
    ]]

    return summary_rows, detail_rows, missing_logs, detail_records


def write_results_csv(path: Path, summary_rows: List[List[object]], detail_rows: List[List[object]]) -> None:
    headers = [
        "record_type",
        "log_id",
        "request_id",
        "prompt",
        "mode",
        "http_status",
        "client_duration_ms",
        "provider_id",
        "provider_name",
        "model_id",
        "model_name",
        "ttft_ms",
        "total_latency_ms",
        "response_text",
        "error",
        "total_requests",
        "successes",
        "errors",
        "avg_ttft_ms",
        "avg_total_latency_ms",
        "slo_attainment",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for row in summary_rows + detail_rows:
            writer.writerow(row + [""] * (len(headers) - len(row)))


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
        summary_rows, detail_rows, missing_logs, detail_records = build_rows(results, logs, args.latency_slo_ms)
        write_results_csv(args.output, summary_rows, detail_rows)
        generate_visualizations(args.output, detail_records)
        if missing_logs:
            print(
                f"Warning: expected {len(results)} new log entries but only found {len(logs)}. "
                "Some rows are marked with 'log entry missing'."
            )
        print(f"Completed run. Summary: {len(results)} requests, output stored in {args.output}")
    finally:
        if original_log != "FULL":
            set_log_level(process_id, restore_log)
        print("Restored process log level.")


if __name__ == "__main__":
    main()

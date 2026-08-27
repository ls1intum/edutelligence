#!/usr/bin/env python3
"""Import successful GuideLLM benchmark summaries into Logos."""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "password",
    "secret",
    "token",
}


def redact_secrets(value: Any) -> Any:
    """Remove credential-like fields before benchmark configuration is stored."""
    if isinstance(value, dict):
        return {key: redact_secrets(item) for key, item in value.items() if key.lower() not in _SECRET_KEYS}
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def build_payloads(report: dict[str, Any], model_provider_id: int, dataset: str) -> list[dict[str, Any]]:
    """Convert successful GuideLLM report entries into Logos import payloads."""
    payloads: list[dict[str, Any]] = []
    for benchmark in report.get("benchmarks", []):
        metrics = benchmark.get("metrics", {})
        totals = metrics.get("request_totals", {})
        successful = int(totals.get("successful", 0))
        incomplete = int(totals.get("incomplete", 0))
        errored = int(totals.get("errored", 0))
        total = int(totals.get("total", 0))
        if successful <= 0 or incomplete > 0 or errored > 0 or total <= 0:
            continue

        end_time = benchmark.get("end_time")
        if end_time is None:
            end_time = benchmark.get("scheduler_metrics", {}).get("measure_end_time")

        payload: dict[str, Any] = {
            "model_provider_id": model_provider_id,
            "configuration": {
                "tool": "guidellm",
                "metadata": redact_secrets(report.get("metadata", {})),
                "scenario": redact_secrets(report.get("config", {})),
                "benchmark": redact_secrets(benchmark.get("config", {})),
            },
            "dataset": dataset,
            "sample_size": total,
            "metrics": metrics,
        }
        if end_time is not None:
            payload["recorded_at"] = datetime.fromtimestamp(float(end_time), timezone.utc).isoformat()
        payloads.append(payload)

    return payloads


def post_payload(api_url: str, token: str, payload: dict[str, Any]) -> None:
    """Send one normalized benchmark summary to the Logos webservice."""
    request = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"Logos import failed with HTTP {response.status}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="GuideLLM benchmarks.json")
    parser.add_argument("--model-provider-id", type=int, required=True)
    parser.add_argument("--dataset", required=True, help="Dataset identifier, for example openai/gsm8k")
    parser.add_argument(
        "--api-url",
        default="http://localhost:18082/logosdb/model_benchmarks/import",
        help="Logos benchmark import endpoint",
    )
    parser.add_argument("--token-env", default="LOGOS_BENCHMARK_TOKEN")
    args = parser.parse_args()

    token = os.environ.get(args.token_env)
    if not token:
        parser.error(f"Set the admin access token in {args.token_env}")

    report = json.loads(args.report.read_text(encoding="utf-8"))
    payloads = build_payloads(report, args.model_provider_id, args.dataset)
    if not payloads:
        parser.error("The GuideLLM report contains no fully successful benchmark summary")
    for payload in payloads:
        post_payload(args.api_url, token, payload)
    print(f"Imported {len(payloads)} successful GuideLLM benchmark summaries")


if __name__ == "__main__":
    main()

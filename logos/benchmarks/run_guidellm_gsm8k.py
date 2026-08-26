#!/usr/bin/env python3
"""Run a small GuideLLM GSM8K benchmark and import its summary into Logos."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DATASET = "openai/gsm8k"


def positive_int(value: str) -> int:
    """Parse a strictly positive integer CLI argument."""
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def build_scenario(
    *,
    target: str,
    model: str,
    provider_token: str | None,
    samples: int,
    max_output_tokens: int,
    report_path: Path,
) -> dict[str, Any]:
    """Build the reproducible GuideLLM scenario for one provider-model pair."""
    backend: dict[str, Any] = {
        "kind": "openai_http",
        "target": target.rstrip("/"),
        "model": model,
        "request_format": "/v1/chat/completions",
        "extras": {"body": {"max_tokens": max_output_tokens}},
    }
    if provider_token:
        backend["api_key"] = provider_token

    return {
        "metadata": {
            "labels": {
                "dataset": DEFAULT_DATASET,
                "purpose": "logos-model-provider-performance",
            }
        },
        "spec": {
            "backend": backend,
            "profile": {"kind": "synchronous"},
            "constraints": [
                {"kind": "max_requests", "count": samples},
                {"kind": "max_errors", "count": 1},
            ],
            "data": [
                {
                    "kind": "huggingface",
                    "source": DEFAULT_DATASET,
                    "load_kwargs": {"name": "main", "split": "test"},
                }
            ],
            "data_column_mapper": {
                "kind": "generative_column_mapper",
                "column_mappings": {"text_column": "question"},
            },
            "data_loader": {
                "kind": "pytorch",
                "samples": samples,
                "shuffle": False,
            },
            "seed": {"kind": "static", "value": 42},
            "metrics": {"kind": "generative", "sample_size": 0},
            "outputs": [{"kind": "json", "path": str(report_path)}],
        },
    }


def default_output_dir(model_provider_id: int | None, model: str) -> Path:
    """Create a unique default directory so previous runs are never overwritten."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    identifier = f"pair-{model_provider_id}" if model_provider_id is not None else model.replace("/", "-")
    return Path("benchmark_results") / "guidellm" / f"{timestamp}-{identifier}"


def validate_successful_report(report_path: Path, expected_samples: int) -> None:
    """Reject reports without one complete, error-free benchmark."""
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read GuideLLM report {report_path}: {exc}") from exc

    failure_details: list[str] = []
    for benchmark in report.get("benchmarks", []):
        metrics = benchmark.get("metrics", {})
        totals = metrics.get("request_totals", {})
        successful = int(totals.get("successful", 0))
        incomplete = int(totals.get("incomplete", 0))
        errored = int(totals.get("errored", 0))
        total = int(totals.get("total", 0))
        if (
            successful == expected_samples
            and total == expected_samples
            and incomplete == 0
            and errored == 0
        ):
            return

        failure_details.append(
            f"successful={successful}/{expected_samples}, incomplete={incomplete}, errored={errored}"
        )
        for request in benchmark.get("requests", {}).get("errored", []):
            error = request.get("info", {}).get("error")
            if error:
                failure_details.append(str(error))
                break

    detail = "; ".join(failure_details) or "no benchmark results"
    raise RuntimeError(f"GuideLLM benchmark failed: {detail}. Report kept at {report_path}")


def run(args: argparse.Namespace) -> Path:
    """Execute GuideLLM and then reuse the existing Logos summary importer."""
    guidellm_bin = shutil.which(args.guidellm_bin)
    if guidellm_bin is None:
        raise RuntimeError(
            f"GuideLLM executable '{args.guidellm_bin}' not found. "
            "Install requirements-guidellm.txt and activate that environment."
        )

    provider_token = None
    if not args.no_provider_auth:
        provider_token = os.environ.get(args.provider_token_env)
        if not provider_token:
            raise RuntimeError(
                f"Set the provider token in {args.provider_token_env}, "
                "or pass --no-provider-auth for an unauthenticated local endpoint."
            )

    if not args.no_import and args.model_provider_id is None:
        raise RuntimeError("--model-provider-id is required unless --no-import is used")

    if not args.no_import and not os.environ.get(args.logos_token_env):
        raise RuntimeError(f"Set the Logos admin token in {args.logos_token_env}")

    output_dir = args.output_dir or default_output_dir(args.model_provider_id, args.model)
    output_dir.mkdir(parents=True, exist_ok=False)
    report_path = (output_dir / "benchmarks.json").resolve()
    scenario = build_scenario(
        target=args.target,
        model=args.model,
        provider_token=provider_token,
        samples=args.samples,
        max_output_tokens=args.max_output_tokens,
        report_path=report_path,
    )

    scenario_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", prefix="logos-guidellm-", delete=False
        ) as scenario_file:
            json.dump(scenario, scenario_file)
            scenario_path = Path(scenario_file.name)
        scenario_path.chmod(0o600)

        pair_label = args.model_provider_id if args.model_provider_id is not None else "not imported"
        print(
            f"Running GuideLLM: pair={pair_label}, model={args.model}, "
            f"dataset={DEFAULT_DATASET}, samples={args.samples}"
        )
        guidellm_env = os.environ.copy()
        if sys.platform == "darwin":
            guidellm_env.setdefault("GUIDELLM__MP_CONTEXT_TYPE", "spawn")
        subprocess.run(
            [guidellm_bin, "run", "--config", str(scenario_path)],
            check=True,
            env=guidellm_env,
        )
    finally:
        if scenario_path is not None:
            scenario_path.unlink(missing_ok=True)

    if not report_path.is_file():
        raise RuntimeError(f"GuideLLM did not create {report_path}")

    validate_successful_report(report_path, args.samples)

    if args.no_import:
        return report_path

    importer = Path(__file__).with_name("import_guidellm_results.py")
    subprocess.run(
        [
            sys.executable,
            str(importer),
            str(report_path),
            "--model-provider-id",
            str(args.model_provider_id),
            "--dataset",
            DEFAULT_DATASET,
            "--api-url",
            args.logos_api_url,
            "--token-env",
            args.logos_token_env,
        ],
        check=True,
    )
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-provider-id", type=positive_int)
    parser.add_argument("--target", required=True, help="OpenAI-compatible base URL")
    parser.add_argument("--model", required=True, help="Model name expected by the provider")
    parser.add_argument("--samples", type=positive_int, default=100)
    parser.add_argument("--max-output-tokens", type=positive_int, default=512)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--provider-token-env", default="MODEL_PROVIDER_API_KEY")
    parser.add_argument("--no-provider-auth", action="store_true")
    parser.add_argument("--logos-token-env", default="LOGOS_BENCHMARK_TOKEN")
    parser.add_argument(
        "--no-import",
        action="store_true",
        help="Keep benchmarks.json locally without calling the Logos import endpoint",
    )
    parser.add_argument(
        "--logos-api-url",
        default="http://localhost:18082/logosdb/model_benchmarks/import",
    )
    parser.add_argument("--guidellm-bin", default="guidellm")
    args = parser.parse_args()

    if not args.target.startswith(("http://", "https://")):
        parser.error("--target must start with http:// or https://")

    try:
        report_path = run(args)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"error: {exc}\n")
    outcome = "saved locally" if args.no_import else "imported successfully"
    print(f"Benchmark {outcome}. Local report: {report_path}")


if __name__ == "__main__":
    main()

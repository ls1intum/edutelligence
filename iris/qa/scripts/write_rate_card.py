"""Build a validated CI rate card from protected GitHub environment variables."""

from __future__ import annotations

import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml


def rate(name: str) -> str:
    value = os.environ.get(name, "")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{name} must be a decimal") from error
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"{name} must be a finite positive decimal")
    return str(parsed)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: write_rate_card.py OUTPUT")
    source = os.environ.get("IRIS_QA_RATE_SOURCE", "").strip()
    if not source:
        raise ValueError(
            "IRIS_QA_RATE_SOURCE must name the verified Azure price source"
        )
    payload = {
        "confirmed_azure_rates": True,
        "source": source,
        "candidates": [
            {
                "model": "gpt-5.4-mini",
                "input_per_million": rate("IRIS_QA_GPT_54_MINI_INPUT_RATE"),
                "output_per_million": rate("IRIS_QA_GPT_54_MINI_OUTPUT_RATE"),
            },
            {
                "model": "gpt-5.5",
                "input_per_million": rate("IRIS_QA_GPT_55_INPUT_RATE"),
                "output_per_million": rate("IRIS_QA_GPT_55_OUTPUT_RATE"),
            },
        ],
        "judge": {
            "model": "gpt-5.4",
            "input_per_million": rate("IRIS_QA_JUDGE_INPUT_RATE"),
            "output_per_million": rate("IRIS_QA_JUDGE_OUTPUT_RATE"),
        },
        "auxiliary": {
            "model": "gpt-5.4-mini",
            "input_per_million": rate("IRIS_QA_GPT_54_MINI_INPUT_RATE"),
            "output_per_million": rate("IRIS_QA_GPT_54_MINI_OUTPUT_RATE"),
        },
    }
    path = Path(sys.argv[1])
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    path.chmod(0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

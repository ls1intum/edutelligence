"""Tests for the GuideLLM summary importer."""

import importlib.util
import sys
from pathlib import Path

_IMPORTER_PATH = Path(__file__).resolve().parent.parent / "import_guidellm_results.py"
_spec = importlib.util.spec_from_file_location("guidellm_importer_under_test", _IMPORTER_PATH)
importer = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = importer
_spec.loader.exec_module(importer)


def test_build_payloads_keeps_only_successful_benchmarks():
    report = {
        "metadata": {"version": 2, "guidellm_version": "0.7.0"},
        "config": {"profile": {"kind": "sweep"}},
        "benchmarks": [
            {
                "config": {"rate": 2},
                "end_time": 1_700_000_000,
                "metrics": {
                    "request_totals": {"successful": 10, "incomplete": 0, "errored": 0, "total": 10},
                    "time_to_first_token_ms": {"successful": {"p50": 120.0}},
                },
            },
            {
                "config": {"rate": 4},
                "metrics": {
                    "request_totals": {"successful": 9, "incomplete": 0, "errored": 1, "total": 10}
                },
            },
        ],
    }

    payloads = importer.build_payloads(report, model_provider_id=7, dataset="openai/gsm8k")

    assert len(payloads) == 1
    assert payloads[0]["model_provider_id"] == 7
    assert payloads[0]["dataset"] == "openai/gsm8k"
    assert payloads[0]["sample_size"] == 10
    assert payloads[0]["configuration"]["tool"] == "guidellm"
    assert payloads[0]["configuration"]["metadata"]["guidellm_version"] == "0.7.0"
    assert payloads[0]["configuration"]["benchmark"] == {"rate": 2}
    assert payloads[0]["metrics"]["time_to_first_token_ms"]["successful"]["p50"] == 120.0
    assert payloads[0]["recorded_at"] == "2023-11-14T22:13:20+00:00"

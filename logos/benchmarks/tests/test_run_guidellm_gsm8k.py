"""Tests for the GuideLLM GSM8K runner configuration."""

import importlib.util
import sys
from pathlib import Path


_RUNNER_PATH = Path(__file__).resolve().parent.parent / "run_guidellm_gsm8k.py"
_spec = importlib.util.spec_from_file_location("guidellm_runner_under_test", _RUNNER_PATH)
runner = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = runner
_spec.loader.exec_module(runner)


def test_build_scenario_is_reproducible_and_summary_only(tmp_path):
    report_path = tmp_path / "benchmarks.json"

    scenario = runner.build_scenario(
        target="https://provider.example/v1/",
        model="Qwen/Qwen3-8B",
        provider_token="secret",
        samples=25,
        max_output_tokens=512,
        report_path=report_path,
    )

    spec = scenario["spec"]
    assert spec["backend"]["target"] == "https://provider.example/v1"
    assert spec["backend"]["model"] == "Qwen/Qwen3-8B"
    assert spec["backend"]["api_key"] == "secret"
    assert spec["data"][0]["source"] == "openai/gsm8k"
    assert spec["data_loader"]["samples"] == 25
    assert spec["constraints"][0] == {"kind": "max_requests", "count": 25}
    assert spec["seed"] == {"kind": "static", "value": 42}
    assert spec["metrics"] == {"kind": "generative", "sample_size": 0}
    assert spec["outputs"] == [{"kind": "json", "path": str(report_path)}]

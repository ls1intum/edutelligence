"""Tests for the GuideLLM GSM8K runner configuration."""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest

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


def test_run_can_keep_report_without_import(monkeypatch, tmp_path):
    output_dir = tmp_path / "run"
    subprocess_calls = []

    def fake_subprocess_run(command, check, env=None):
        subprocess_calls.append((command, env))
        scenario_path = Path(command[3])
        scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
        report_path = Path(scenario["spec"]["outputs"][0]["path"])
        report_path.write_text(
            json.dumps(
                {
                    "benchmarks": [
                        {
                            "metrics": {
                                "request_totals": {
                                    "successful": 5,
                                    "incomplete": 0,
                                    "errored": 0,
                                    "total": 5,
                                }
                            }
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(runner.shutil, "which", lambda _: "/test/guidellm")
    monkeypatch.setattr(runner.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(runner.sys, "platform", "darwin")

    args = argparse.Namespace(
        guidellm_bin="guidellm",
        no_provider_auth=True,
        provider_token_env="MODEL_PROVIDER_API_KEY",
        no_import=True,
        model_provider_id=None,
        logos_token_env="LOGOS_BENCHMARK_TOKEN",
        output_dir=output_dir,
        target="https://logos-dev.aet.cit.tum.de/v1",
        model="Qwen/Qwen2.5-Coder-7B-Instruct-AWQ",
        samples=5,
        max_output_tokens=512,
        logos_api_url="unused",
    )

    report_path = runner.run(args)

    assert report_path == (output_dir / "benchmarks.json").resolve()
    assert len(subprocess_calls) == 1
    assert subprocess_calls[0][1]["GUIDELLM__MP_CONTEXT_TYPE"] == "spawn"


def test_validate_successful_report_surfaces_request_error(tmp_path):
    report_path = tmp_path / "benchmarks.json"
    report_path.write_text(
        json.dumps(
            {
                "benchmarks": [
                    {
                        "metrics": {
                            "request_totals": {
                                "successful": 0,
                                "incomplete": 0,
                                "errored": 1,
                                "total": 1,
                            }
                        },
                        "requests": {"errored": [{"info": {"error": "404 model not available for this key"}}]},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="404 model not available"):
        runner.validate_successful_report(report_path, expected_samples=5)

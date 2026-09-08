from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from logos.benchmarks import huggingface_datasets as hf
from logos.benchmarks.configuration import BenchmarkSettings
from logos.benchmarks.guidellm_runner import build_scenario


def test_custom_dataset_and_concurrency_are_used_in_scenario():
    scenario = build_scenario(
        target="http://localhost",
        model="model",
        api_key=None,
        samples=12,
        max_output_tokens=128,
        report_path=Path("report.json"),
        settings=BenchmarkSettings(
            dataset="org/data",
            subset="default",
            split="train",
            text_column="prompt",
            profile="concurrent",
            concurrency=4,
            seed=17,
        ),
    )
    spec = scenario["spec"]
    assert spec["data"][0] == {
        "kind": "huggingface",
        "source": "org/data",
        "load_kwargs": {"name": "default", "split": "train"},
    }
    assert spec["data_column_mapper"]["column_mappings"]["text_column"] == "prompt"
    assert spec["profile"] == {"kind": "concurrent", "streams": 4}
    assert spec["seed"]["value"] == 17
    assert spec["backend"]["extras"]["body"]["max_tokens"] == 128


@pytest.mark.parametrize(
    "settings",
    [
        {"dataset": "/tmp/data"},
        {"dataset": "https://other/data"},
        {"concurrency": 0},
        {"concurrency": 1000},
        {"seed": -1},
        {"profile": "unknown"},
        {"serving_overrides": {"vllm_binary": "/tmp/program"}},
    ],
)
def test_invalid_settings_are_rejected(settings):
    with pytest.raises(ValidationError):
        BenchmarkSettings(**settings)


async def test_metadata_selects_defaults_and_only_text_columns(monkeypatch):
    get = AsyncMock(
        side_effect=[
            {"splits": [{"config": "main", "split": "train"}, {"config": "main", "split": "test"}]},
            {
                "features": [
                    {"name": "question", "type": {"dtype": "string"}},
                    {"name": "messages", "type": [{"role": "string"}]},
                    {"name": "label", "type": {"dtype": "int64"}},
                ]
            },
        ]
    )
    monkeypatch.setattr(hf, "_get_json", get)
    result = await hf.dataset_metadata("openai/gsm8k")
    assert result["subset"] == "main"
    assert result["split"] == "test"
    assert result["text_columns"] == ["question"]
    assert result["preview_rows"] == []
    assert get.await_args.args[1] == {"dataset": "openai/gsm8k", "config": "main", "split": "test"}


async def test_metadata_rejects_unknown_split_before_preview(monkeypatch):
    get = AsyncMock(return_value={"splits": [{"config": "main", "split": "test"}]})
    monkeypatch.setattr(hf, "_get_json", get)
    with pytest.raises(HTTPException, match="does not exist"):
        await hf.dataset_metadata("openai/gsm8k", "main", "missing")
    assert get.await_count == 1


async def test_metadata_preview_is_bounded_and_preserves_structured_answers(monkeypatch):
    get = AsyncMock(
        side_effect=[
            {"splits": [{"config": "main", "split": "test"}]},
            {
                "features": [
                    {"name": "question", "type": {"dtype": "string"}},
                    {"name": "answers", "type": {"_type": "List"}},
                    {"name": "image", "type": {"_type": "Image"}},
                ],
                "rows": [
                    {
                        "row_idx": i,
                        "row": {
                            "question": "Q" * 2100,
                            "answers": ["<b>Answer</b>"],
                            "image": {"src": "https://example.org/picture"},
                        },
                        "truncated_cells": ["answers"],
                    }
                    for i in range(8)
                ],
            },
        ]
    )
    monkeypatch.setattr(hf, "_get_json", get)
    result = await hf.dataset_metadata("org/dataset")
    assert result["preview_columns"] == ["question", "answers"]
    assert len(result["preview_rows"]) == 5
    assert result["preview_rows"][0] == {
        "row_index": 0,
        "cells": {"question": "Q" * 2000, "answers": '["<b>Answer</b>"]'},
        "truncated_columns": ["question", "answers"],
    }
    assert get.await_count == 2  # Preview reuses the existing metadata request.


async def test_metadata_preview_handles_missing_cells(monkeypatch):
    features = [{"name": "prompt", "type": {"dtype": "string"}}]
    get = AsyncMock(
        side_effect=[
            {"splits": [{"config": "default", "split": "train"}]},
            {"features": features, "rows": [{"row_idx": 0, "row": {}}]},
        ]
    )
    monkeypatch.setattr(hf, "_get_json", get)
    result = await hf.dataset_metadata("org/dataset")
    assert result["preview_rows"][0]["cells"]["prompt"] is None


def test_serving_overrides_preserve_unrelated_flags_and_replace_old_values():
    from logos.benchmarks.configuration import ServingOverrides
    from logos.benchmarks.guidellm_runner import apply_serving_overrides, extract_serving_configuration

    current = {
        "dtype": "auto",
        "enable_sleep_mode": True,
        "extra_args": ["--pipeline-parallel-size=2", "--max-num-batched-tokens", "1024", "--other", "x"],
    }
    result = apply_serving_overrides(
        current,
        ServingOverrides(
            tensor_parallel_size=2, pipeline_parallel_size=4, max_num_batched_tokens=2048, hf_overrides={"key": 1}
        ),
    )
    assert result["enable_sleep_mode"] is True
    assert result["extra_args"] == [
        "--other",
        "x",
        "--pipeline-parallel-size",
        "4",
        "--max-num-batched-tokens",
        "2048",
        "--hf-overrides",
        '{"key": 1}',
    ]
    assert current["extra_args"][0] == "--pipeline-parallel-size=2"
    snapshot = {"runtime": {"lanes": [{"model": "m", "lane_config": {"vllm_config": result}}]}}
    captured = extract_serving_configuration(snapshot, "m")
    assert captured["pipeline_parallel_size"] == 4
    assert captured["max_num_batched_tokens"] == 2048
    assert captured["hf_overrides"] == {"key": 1}

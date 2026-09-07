from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from logos.benchmarks.configuration import BenchmarkSettings
from logos.benchmarks.guidellm_runner import build_scenario
from logos.benchmarks import huggingface_datasets as hf


def test_custom_dataset_and_concurrency_are_used_in_scenario():
    scenario = build_scenario(target="http://localhost", model="model", api_key=None,
        samples=12, max_output_tokens=128, report_path=Path("report.json"),
        settings=BenchmarkSettings(dataset="org/data", subset="default", split="train",
                                   text_column="prompt", profile="concurrent", concurrency=4, seed=17))
    spec = scenario["spec"]
    assert spec["data"][0] == {"kind": "huggingface", "source": "org/data",
                              "load_kwargs": {"name": "default", "split": "train"}}
    assert spec["data_column_mapper"]["column_mappings"]["text_column"] == "prompt"
    assert spec["profile"] == {"kind": "concurrent", "streams": 4}
    assert spec["seed"]["value"] == 17
    assert spec["backend"]["extras"]["body"]["max_tokens"] == 128


@pytest.mark.parametrize("settings", [{"dataset": "/tmp/data"}, {"dataset": "https://other/data"},
    {"concurrency": 0}, {"concurrency": 1000}, {"seed": -1}, {"profile": "unknown"},
    {"serving_overrides": {"vllm_binary": "/tmp/program"}}])
def test_invalid_settings_are_rejected(settings):
    with pytest.raises(ValidationError):
        BenchmarkSettings(**settings)


async def test_metadata_selects_defaults_and_only_text_columns(monkeypatch):
    get = AsyncMock(side_effect=[{"splits": [{"config": "main", "split": "train"}, {"config": "main", "split": "test"}]},
        {"features": [{"name": "question", "type": {"dtype": "string"}},
                      {"name": "messages", "type": [{"role": "string"}]},
                      {"name": "label", "type": {"dtype": "int64"}}]}])
    monkeypatch.setattr(hf, "_get_json", get)
    result = await hf.dataset_metadata("openai/gsm8k")
    assert result["subset"] == "main"
    assert result["split"] == "test"
    assert result["text_columns"] == ["question"]
    assert get.await_args.args[1] == {"dataset": "openai/gsm8k", "config": "main", "split": "test"}


async def test_metadata_rejects_unknown_split_before_preview(monkeypatch):
    get = AsyncMock(return_value={"splits": [{"config": "main", "split": "test"}]})
    monkeypatch.setattr(hf, "_get_json", get)
    with pytest.raises(HTTPException, match="does not exist"):
        await hf.dataset_metadata("openai/gsm8k", "main", "missing")
    assert get.await_count == 1

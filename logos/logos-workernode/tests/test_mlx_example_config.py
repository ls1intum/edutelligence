"""The reference configuration in config.example.mlx.yml must stay serveable.

MACOS.md's worked example tells operators to point the node at whatever this
file advertises, so the file is a contract, not just a sample: it must parse
as an ``AppConfig``, and every advertised model must carry both a capacity
profile (or main.py drops it from the advertised capabilities) and a vLLM
``model_overrides`` entry (or its lane spawns without the ``max_model_len``
cap and does not fit — the Qwen3.8 hybrid sizes its KV cache against the
model's full 262144 window).
"""

from __future__ import annotations

import pytest

from logos_worker_node import config as worker_config

EXAMPLE_CONFIG = "config.example.mlx.yml"


@pytest.fixture
def example_config(monkeypatch, tmp_path):
    from pathlib import Path

    monkeypatch.setenv("LOGOS_WORKER_NODE_CONFIG", str(Path(__file__).resolve().parents[1] / EXAMPLE_CONFIG))
    # Pre-set so the lift is a no-op and cannot leak across tests; the
    # expansion itself is covered in test_main.py.
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.setattr(worker_config, "_config", None, raising=False)

    from logos_worker_node.config import load_config

    return load_config()


def test_example_config_parses(example_config) -> None:
    assert example_config.logos.capabilities_models


def test_every_advertised_model_is_serveable(example_config) -> None:
    profiles = example_config.model_profile_overrides
    overrides = example_config.engines.vllm.model_overrides
    for model in example_config.logos.capabilities_models:
        profile = profiles.get(model)
        assert (
            profile
        ), f"{model} advertised without a model_profile_overrides entry — it would be dropped from the capabilities"
        assert (
            profile.get("base_residency_mb") or 0
        ) > 0, f"{model} profile has no base_residency_mb — it would advertise as uncalibrated"
        assert overrides.get(
            model
        ), f"{model} advertised without a model_overrides entry — its lane would spawn without the max_model_len cap"

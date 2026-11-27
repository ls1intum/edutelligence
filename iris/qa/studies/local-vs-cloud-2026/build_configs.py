"""Build one application.yml per study configuration plus one llm_config.yml.

Usage: build_configs.py PRODCFG_DIR KEYS_DIR OUT_DIR

PRODCFG_DIR holds copies of the production files as application.prod.yml and
llm_config.prod.yml. KEYS_DIR holds logos.key (the study's own Logos key) and,
optionally, anthropic.key. Only model ids in existing role rows change, so every
configuration runs production Iris with production settings except the model
under test. OUT_DIR receives secrets: keep it outside the repository.
"""

import copy
import os
import sys
from pathlib import Path

import yaml

TIMEOUT = 300.0
LOGOS = "https://logos.aet.cit.tum.de/v1"


def main() -> None:
    prod, keys, out = map(Path, sys.argv[1:4])
    logos_key = (keys / "logos.key").read_text(encoding="utf-8").strip()
    anthropic_file = keys / "anthropic.key"
    anthropic_key = (
        anthropic_file.read_text(encoding="utf-8").strip()
        if anthropic_file.exists()
        else "unused-not-a-key"
    )
    app = yaml.safe_load((prod / "application.prod.yml").read_text(encoding="utf-8"))
    models = yaml.safe_load((prod / "llm_config.prod.yml").read_text(encoding="utf-8"))

    # Secrets and live services the study must not touch.
    app["api_keys"] = [{"token": "qa-local-only"}]  # nosec B105 - placeholder
    app["langfuse"] = {"enabled": False}
    app.pop("memiris", None)
    app["weaviate"] = {"host": "weaviate.invalid", "port": 443, "grpc_port": 50051}
    app["env_vars"] = {
        key: value
        for key, value in (app.get("env_vars") or {}).items()
        if not key.startswith("SENTRY")
    }
    app["local_llm_enabled"] = True

    for entry in models:
        if "logos.aet.cit.tum.de" in str(entry.get("base_url", "")):
            entry["api_key"] = logos_key
        elif "api_key" in entry:
            # Never called by the study.
            entry["api_key"] = "qa-unused-not-a-key"  # pragma: allowlist secret
        if entry["type"] == "openai_chat":
            entry["request_timeout_seconds"] = TIMEOUT

    # Production lists only the cloud reranker; give it the local one as well.
    for variants in app["llm_configuration"].values():
        for roles in variants.values():
            if isinstance(roles, dict) and roles.get("reranker") == "cohere":
                roles["reranker"] = {
                    "local": "Qwen/Qwen3-Reranker-8B",
                    "cloud": "cohere",
                }

    # Pin the study's cloud chat models: C1 (default) is Luna and C2 (advanced) is
    # Sol, whatever production uses today (production moved to Terra on 2026-11-02).
    chat = app["llm_configuration"]["chat_pipeline"]
    chat["default"]["chat"]["cloud"] = "gpt-6-luna-medium"
    chat["advanced"]["chat"]["cloud"] = "gpt-6.1-sol-medium"

    models = models + _extra_models(models, logos_key, anthropic_key)
    configs = {"base": copy.deepcopy(app)}
    for name, target in (
        ("gptoss", "bench-gpt-oss-120b"),
        ("gemma", "bench-gemma-4"),
        ("gemmathink", "bench-gemma-4-think"),
    ):
        configs[name] = copy.deepcopy(app)
        _swap_local(configs[name], target)
    for name, target in (
        ("terra", "bench-gpt-6.1-terra-medium"),
        ("opus", "bench-claude-opus-5-5"),
        ("sonnet", "bench-claude-sonnet-5-5"),
    ):
        configs[name] = copy.deepcopy(app)
        _swap_chat_cloud(configs[name], target)

    old = os.umask(0o077)
    out.mkdir(parents=True, exist_ok=True)
    (out / "llm_config.yml").write_text(
        yaml.safe_dump(models, sort_keys=False), encoding="utf-8"
    )
    for name, application in configs.items():
        (out / f"application.{name}.yml").write_text(
            yaml.safe_dump(application, sort_keys=False), encoding="utf-8"
        )
    os.umask(old)
    print("wrote", sorted(path.name for path in out.iterdir()))


def _extra_models(models: list[dict], logos_key: str, anthropic_key: str) -> list[dict]:
    gemma = {
        "id": "bench-gemma-4",
        "name": "Gemma 4 31B (study)",
        "description": "google/gemma-4-31B-it via Logos (Morpheus)",
        "type": "openai_chat",
        "model": "google/gemma-4-31B-it",
        "base_url": LOGOS,
        "api_key": logos_key,
        "supports_temperature": True,
        "use_responses_api": False,
        "request_timeout_seconds": TIMEOUT,
        "cost_per_million_input_token": 0,  # nosec B105 - a price, not a token
        "cost_per_million_output_token": 0,  # nosec B105 - a price, not a token
    }
    # Gemma 4 thinks only when asked; it has no levels, only on and off.
    gemma_think = {
        **copy.deepcopy(gemma),
        "id": "bench-gemma-4-think",
        "name": "Gemma 4 31B thinking (study)",
        "extra_body": {"chat_template_kwargs": {"enable_thinking": True}},
    }
    gpt_oss = {
        "id": "bench-gpt-oss-120b",
        "name": "gpt-oss-120b (study, medium)",
        "description": "gpt-oss-120b on Logos, reasoning effort medium",
        "type": "openai_chat",
        "model": "openai/gpt-oss-120b",
        "base_url": LOGOS,
        "api_key": logos_key,
        "supports_temperature": False,
        "supports_reasoning_effort": True,
        "reasoning_effort": "medium",
        "reasoning_effort_values": ["low", "medium", "high"],
        "use_responses_api": False,
        "request_timeout_seconds": TIMEOUT,
        "cost_per_million_input_token": 0,  # nosec B105 - a price, not a token
        "cost_per_million_output_token": 0,  # nosec B105 - a price, not a token
    }
    # Same shape as production's gpt-6.1-sol-medium; prices are the OpenAI list
    # prices (1.00 / 0.05 / 1.25 / 5.00 USD) times 0.891, like the production rows.
    terra = copy.deepcopy(next(e for e in models if e["id"] == "gpt-6.1-sol-medium"))
    terra.update(
        id="bench-gpt-6.1-terra-medium",
        name="GPT 6.1 Terra (medium effort, study)",
        description="GPT 6.1 Terra via Logos (Responses API), medium reasoning effort",
        model="gpt-6.1-terra",
        reasoning_effort="medium",
        cost_per_million_input_token=0.891,
        cost_per_million_cached_input_token=0.0446,
        cost_per_million_cache_write_input_token=1.1138,
        cost_per_million_output_token=4.455,
    )
    extra = [gpt_oss, gemma, gemma_think, terra]
    for model, cost_in, cost_out in (
        ("claude-opus-5-5", 4.0, 20.0),
        ("claude-sonnet-5-5", 2.0, 10.0),
    ):
        extra.append(
            {
                "id": f"bench-{model}",
                "name": f"{model} (study)",
                "description": "Anthropic OpenAI-compatible endpoint, study only",
                "type": "openai_chat",
                "model": model,
                "base_url": "https://api.anthropic.com/v1/",
                "api_key": anthropic_key,
                "supports_temperature": False,
                "supports_reasoning_effort": True,
                "reasoning_effort": "medium",
                "reasoning_effort_values": ["low", "medium", "high"],
                "use_responses_api": False,
                "supports_structured_output": False,
                "request_timeout_seconds": TIMEOUT,
                "cost_per_million_input_token": cost_in,
                "cost_per_million_output_token": cost_out,
            }
        )
    return extra


def _swap_local(application: dict, target: str) -> None:
    """Point every local Qwen chat-model row at target (embedding and reranker stay)."""
    for variants in application["llm_configuration"].values():
        for roles in variants.values():
            for role, value in roles.items():
                if role in ("embedding", "reranker"):
                    continue
                if isinstance(value, dict) and str(value.get("local", "")).startswith(
                    "Qwen/Qwen3.8"
                ):
                    value["local"] = target


def _swap_chat_cloud(application: dict, target: str) -> None:
    for variant in application["llm_configuration"]["chat_pipeline"].values():
        variant["chat"]["cloud"] = target


if __name__ == "__main__":
    main()

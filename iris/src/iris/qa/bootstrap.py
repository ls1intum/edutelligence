from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml

from iris.qa.yaml_utils import safe_load_unique


@dataclass
class WorkerConfiguration:
    directory: tempfile.TemporaryDirectory
    environment: dict[str, str]

    def close(self) -> None:
        self.directory.cleanup()


def apply_local_llm_config(path: Path) -> dict[str, str]:
    """Load one unambiguous Azure chat credential from an Iris LLM config.

    This is a local-development convenience. The weekly workflow deliberately
    keeps using workload identity and never reads a credential-bearing file.
    """
    try:
        payload = safe_load_unique(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(
            f"Cannot read local LLM configuration {path}: {error}"
        ) from error
    if not isinstance(payload, list):
        raise ValueError("Local LLM configuration must contain a YAML list")

    resources: dict[str, dict[str, set[str]]] = {}
    api_versions: dict[str, list[str]] = {}
    deployments: dict[str, dict[str, set[str]]] = {}
    for entry in payload:
        if not isinstance(entry, dict) or entry.get("type") != "azure_chat":
            continue
        endpoint = str(entry.get("endpoint", "")).strip()
        parsed = urlparse(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.hostname.endswith(".openai.azure.com")
        ):
            continue
        resource_endpoint = f"https://{parsed.hostname}"
        key = str(entry.get("api_key", "")).strip()
        if not key:
            continue
        resource = resources.setdefault(
            resource_endpoint,
            {"keys": set(), "models": set()},
        )
        resource["keys"].add(key)
        model = str(entry.get("model", "")).strip()
        resource["models"].add(model)
        deployment = str(entry.get("azure_deployment", "")).strip()
        if model and deployment:
            deployments.setdefault(resource_endpoint, {}).setdefault(model, set()).add(
                deployment
            )
        api_version = str(entry.get("api_version", "")).strip()
        if api_version:
            api_versions.setdefault(resource_endpoint, []).append(api_version)

    if len(resources) != 1:
        raise ValueError(
            "Local LLM configuration must contain exactly one credential-bearing "
            "Azure chat resource"
        )
    endpoint, resource = next(iter(resources.items()))
    if len(resource["keys"]) != 1:
        raise ValueError(
            "Local LLM configuration contains multiple credentials for its Azure "
            "chat resource; make the intended credential unambiguous"
        )
    key = next(iter(resource["keys"]))
    versions = api_versions.get(endpoint, [])
    api_version = max(versions, default="2025-04-01-preview")

    requested_deployments = {}
    for model in ("gpt-5.4-mini", "gpt-5.5", "gpt-5.4"):
        candidates = deployments.get(endpoint, {}).get(model, set())
        if len(candidates) > 1:
            raise ValueError(
                f"Local LLM configuration contains multiple deployments for {model}"
            )
        requested_deployments[model] = next(iter(candidates), model)

    configured = {
        "IRIS_QA_AZURE_ENDPOINT": endpoint,
        "IRIS_QA_AZURE_AUTH_MODE": "api_key",
        "IRIS_QA_AZURE_API_KEY": key,
        "IRIS_QA_AZURE_API_VERSION": api_version,
        "IRIS_QA_GPT_54_MINI_DEPLOYMENT": requested_deployments["gpt-5.4-mini"],
        "IRIS_QA_GPT_55_DEPLOYMENT": requested_deployments["gpt-5.5"],
        "IRIS_QA_JUDGE_DEPLOYMENT": requested_deployments["gpt-5.4"],
    }
    os.environ.update(configured)
    return {
        "endpoint": endpoint,
        "apiVersion": api_version,
        "credentialSource": str(path.resolve()),
    }


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Required environment variable {name} is not set")
    return value


def _azure_endpoint() -> str:
    value = _required("IRIS_QA_AZURE_ENDPOINT").rstrip("/")
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("IRIS_QA_AZURE_ENDPOINT has an invalid port") from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".openai.azure.com")
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "IRIS_QA_AZURE_ENDPOINT must be an HTTPS *.openai.azure.com resource "
            "endpoint without credentials, query, fragment, or custom path"
        )
    return value


def _model(
    *,
    model_id: str,
    model: str,
    deployment: str,
    endpoint: str,
    api_version: str,
    auth_mode: str,
    input_rate: str,
    output_rate: str,
    reasoning_effort: str = "medium",
    api_key: str | None = None,
) -> dict:
    entry = {
        "id": model_id,
        "type": "azure_chat",
        "model": model,
        "endpoint": endpoint,
        "azure_deployment": deployment,
        "api_version": api_version,
        "auth_mode": auth_mode,
        "supports_temperature": False,
        "supports_reasoning_effort": True,
        "reasoning_effort": reasoning_effort,
        "reasoning_effort_values": ["none", "low", "medium", "high", "xhigh"],
        "use_responses_api": True,
        "cost_per_million_input_token": float(input_rate),
        "cost_per_million_output_token": float(output_rate),
    }
    if auth_mode == "api_key":
        if not api_key:
            raise ValueError("API-key model configuration requires a local key")
        # The current origin/main schema requires this field. The containing
        # config is a mode-600 temporary file removed when the worker exits.
        entry["api_key"] = api_key  # pragma: allowlist secret
    return entry


def _application(candidate_id: str) -> dict:
    mini = "qa-aux-mini"
    both = {"local": candidate_id, "cloud": candidate_id}
    mini_both = {"local": mini, "cloud": mini}
    return {
        "api_keys": [],
        "env_vars": {},
        "weaviate": {"host": "fixture.invalid", "port": 1, "grpc_port": 1},
        "memiris": {"enabled": False, "sleep_enabled": False},
        "langfuse": {"enabled": False},
        "local_llm_enabled": False,
        "llm_configuration": {
            "chat_pipeline": {
                "default": {"chat": both, "guide": mini_both},
                "advanced": {"chat": both, "guide": mini_both},
            },
            "citation_pipeline": {
                "default": {"chat": mini_both, "keyword_summary": mini_both},
                "advanced": {"chat": mini_both},
            },
            "session_title_generation_pipeline": {"default": {"chat": mini_both}},
            "interaction_suggestion_pipeline": {
                "course": {"chat": mini_both},
                "exercise": {"chat": mini_both},
            },
            "code_feedback_pipeline": {"default": {"chat": mini_both}},
            "mcq_generation_pipeline": {"default": {"chat": mini_both}},
            "tutor_suggestion_pipeline": {
                "default": {"chat": both},
                "advanced": {"chat": both},
            },
            "autonomous_tutor_pipeline": {"default": {"chat": both}},
            "global_search_pipeline": {
                "default": {
                    "hyde": mini_both,
                    "answer": both,
                    "embedding": "qa-fixture",
                }
            },
            "lecture_retrieval_pipeline": {
                "default": {
                    "chat": mini_both,
                    "embedding": "qa-fixture",
                    "reranker": "qa-fixture",
                }
            },
            "lecture_unit_segment_retrieval_pipeline": {
                "default": {
                    "chat": mini_both,
                    "embedding": "qa-fixture",
                    "reranker": "qa-fixture",
                }
            },
            "lecture_transcriptions_retrieval_pipeline": {
                "default": {
                    "chat": mini_both,
                    "embedding": "qa-fixture",
                    "reranker": "qa-fixture",
                }
            },
            "faq_retrieval_pipeline": {
                "default": {"chat": mini_both, "embedding": "qa-fixture"}
            },
        },
    }


def create_worker_configuration(rate_card, candidate_model: str) -> WorkerConfiguration:
    if candidate_model not in {"gpt-5.4-mini", "gpt-5.5"}:
        raise ValueError(f"Unsupported QA candidate model: {candidate_model}")
    endpoint = _azure_endpoint()
    auth_mode = os.environ.get("IRIS_QA_AZURE_AUTH_MODE", "azure_ad")
    if auth_mode not in {"azure_ad", "api_key"}:
        raise ValueError("IRIS_QA_AZURE_AUTH_MODE must be azure_ad or api_key")
    if auth_mode == "api_key":
        _required("IRIS_QA_AZURE_API_KEY")

    deployments = {
        "gpt-5.4-mini": _required("IRIS_QA_GPT_54_MINI_DEPLOYMENT"),
        "gpt-5.4": _required("IRIS_QA_JUDGE_DEPLOYMENT"),
    }
    if candidate_model == "gpt-5.5":
        deployments["gpt-5.5"] = _required("IRIS_QA_GPT_55_DEPLOYMENT")
    if len(set(deployments.values())) != len(deployments):
        raise ValueError("Candidate, auxiliary, and judge deployments must be distinct")
    rates = {rate.model: rate for rate in (*rate_card.candidates, rate_card.judge)}
    api_version = os.environ.get(
        "IRIS_QA_AZURE_API_VERSION", "2025-04-01-preview"
    ).strip()
    if not api_version:
        raise ValueError("IRIS_QA_AZURE_API_VERSION must not be empty")
    local_api_key = os.environ.get("IRIS_QA_AZURE_API_KEY")
    models = [
        _model(
            model_id=(
                "qa-gpt-54-mini"
                if model == "gpt-5.4-mini"
                else ("qa-gpt-55" if model == "gpt-5.5" else "qa-judge")
            ),
            model=model,
            deployment=deployment,
            endpoint=endpoint,
            api_version=api_version,
            auth_mode=auth_mode,
            input_rate=str(rates[model].input_per_million),
            output_rate=str(rates[model].output_per_million),
            api_key=local_api_key if auth_mode == "api_key" else None,
        )
        for model, deployment in deployments.items()
    ]
    mini_rate = rates["gpt-5.4-mini"]
    models.append(
        _model(
            model_id="qa-aux-mini",
            model="gpt-5.4-mini",
            deployment=deployments["gpt-5.4-mini"],
            endpoint=endpoint,
            api_version=api_version,
            auth_mode=auth_mode,
            input_rate=str(mini_rate.input_per_million),
            output_rate=str(mini_rate.output_per_million),
            reasoning_effort="none",
            api_key=local_api_key if auth_mode == "api_key" else None,
        )
    )
    candidate_id = (
        "qa-gpt-54-mini" if candidate_model == "gpt-5.4-mini" else "qa-gpt-55"
    )
    directory = tempfile.TemporaryDirectory(prefix="iris-qa-")
    root = Path(directory.name)
    application = root / "application.yml"
    llm_config = root / "llm-config.yml"
    application.write_text(yaml.safe_dump(_application(candidate_id)), encoding="utf-8")
    llm_config.write_text(yaml.safe_dump(models), encoding="utf-8")
    environment = dict(os.environ)
    environment.update(
        APPLICATION_YML_PATH=str(application),
        LLM_CONFIG_PATH=str(llm_config),
        IRIS_QA_CANDIDATE_MODEL=candidate_model,
    )
    return WorkerConfiguration(directory, environment)

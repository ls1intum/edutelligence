from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml

from iris.qa.yaml_utils import safe_load_unique

CANDIDATE_MODEL_IDS = {
    "gpt-5.4-mini": "qa-gpt-54-mini",
    "gpt-5.5": "qa-gpt-55",
    "gpt-5.6-sol": "qa-gpt-56-sol",
    "gpt-5.6-terra": "qa-gpt-56-terra",
    "gpt-5.6-luna": "qa-gpt-56-luna",
    "openai/gpt-oss-120b": "qa-gpt-oss-120b",
    "gpt-6.1-sol": "qa-gpt-61-sol",
    "gpt-6-luna": "qa-gpt-6-luna",
    "gpt-6.1-sol-medium": "qa-gpt-61-sol-medium",
    "gpt-6-luna-medium": "qa-gpt-6-luna-medium",
    "gpt-6-luna-high": "qa-gpt-6-luna-high",
}
CANDIDATE_DEPLOYMENT_ENV = {
    "gpt-5.4-mini": "IRIS_QA_GPT_54_MINI_DEPLOYMENT",
    "gpt-5.5": "IRIS_QA_GPT_55_DEPLOYMENT",
    "gpt-5.6-sol": "IRIS_QA_GPT_56_SOL_DEPLOYMENT",
    "gpt-5.6-terra": "IRIS_QA_GPT_56_TERRA_DEPLOYMENT",
    "gpt-5.6-luna": "IRIS_QA_GPT_56_LUNA_DEPLOYMENT",
}
DEFAULT_REASONING_MODELS = {
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
}
GPT_OSS_MODEL = "openai/gpt-oss-120b"
LOGOS_CANDIDATES = {
    GPT_OSS_MODEL: {
        "model_env": "IRIS_QA_GPT_OSS_120B_MODEL",
        "reasoning_effort": None,
        "use_responses_api": False,
    },
    "gpt-6.1-sol": {
        "model_env": "IRIS_QA_GPT_61_SOL_MODEL",
        "reasoning_effort": "high",
        "use_responses_api": True,
    },
    "gpt-6-luna": {
        "model_env": "IRIS_QA_GPT_6_LUNA_MODEL",
        "reasoning_effort": "xhigh",
        "use_responses_api": True,
    },
}
# Further reasoning efforts of a Logos candidate, as candidate id -> (model, effort).
# They send the same model with another effort, so the effort is the only difference
# between two candidates of one model.
LOGOS_CANDIDATE_VARIANTS = {
    "gpt-6.1-sol-medium": ("gpt-6.1-sol", "medium"),
    "gpt-6-luna-medium": ("gpt-6-luna", "medium"),
    "gpt-6-luna-high": ("gpt-6-luna", "high"),
}
# Without an Azure resource the helper model that Iris itself calls comes from
# Logos too.
HELPER_ROUTE_ENV = "IRIS_QA_HELPER_ROUTE"
LOGOS_HELPER_MODEL = "gpt-5.4-mini"
LOGOS_ENVIRONMENT_NAMES = (
    HELPER_ROUTE_ENV,
    "IRIS_QA_LOGOS_BASE_URL",
    "IRIS_QA_LOGOS_API_KEY",
    *(entry["model_env"] for entry in LOGOS_CANDIDATES.values()),
)


@dataclass
class WorkerConfiguration:
    directory: tempfile.TemporaryDirectory
    environment: dict[str, str]

    def close(self) -> None:
        self.directory.cleanup()


def apply_local_llm_config(path: Path, *, judge: bool = True) -> dict[str, str]:
    """Load unambiguous Azure and optional Logos credentials from Iris config.

    The Azure judge needs an Azure resource. When the judge is skipped
    (``judge=False``) a configuration with Logos entries only is accepted and the
    helper model comes from Logos.

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
    logos_entries: dict[str, list[tuple[str, str, str]]] = {}
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        if (
            entry.get("type") == "openai_chat"
            and entry.get("model") in LOGOS_CANDIDATES
        ):
            model = str(entry["model"])
            logos_entries.setdefault(model, []).append(
                (
                    str(entry.get("base_url", "")).strip().rstrip("/"),
                    str(entry.get("api_key", "")).strip(),
                    model,
                )
            )
            continue
        if entry.get("type") != "azure_chat":
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

    helper_via_logos = False
    if len(resources) != 1:
        if not judge and not resources and logos_entries:
            helper_via_logos = True
        else:
            raise ValueError(
                "Local LLM configuration must contain exactly one credential-bearing "
                "Azure chat resource"
            )
    configured: dict[str, str] = {}
    endpoint = ""
    api_version = ""
    if helper_via_logos:
        configured[HELPER_ROUTE_ENV] = "logos"
    else:
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
        for model in (*CANDIDATE_DEPLOYMENT_ENV, "gpt-5.4"):
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
            "IRIS_QA_GPT_56_SOL_DEPLOYMENT": requested_deployments["gpt-5.6-sol"],
            "IRIS_QA_GPT_56_TERRA_DEPLOYMENT": requested_deployments["gpt-5.6-terra"],
            "IRIS_QA_GPT_56_LUNA_DEPLOYMENT": requested_deployments["gpt-5.6-luna"],
            "IRIS_QA_JUDGE_DEPLOYMENT": requested_deployments["gpt-5.4"],
        }
    for name in LOGOS_ENVIRONMENT_NAMES:
        os.environ.pop(name, None)
    if logos_entries:
        unique_logos_entries = {
            item for entries in logos_entries.values() for item in entries
        }
        unique_logos_routes = {
            (base_url, key) for base_url, key, _ in unique_logos_entries
        }
        if len(unique_logos_routes) != 1:
            raise ValueError("Local LLM configuration contains multiple Logos routes")
        logos_base_url, logos_key = next(iter(unique_logos_routes))
        _validate_logos_base_url(logos_base_url)
        if not logos_key:
            raise ValueError("Local Logos configuration requires an API key")
        configured.update(
            {
                "IRIS_QA_LOGOS_BASE_URL": logos_base_url,
                "IRIS_QA_LOGOS_API_KEY": logos_key,
            }
        )
        for model, entries in logos_entries.items():
            if len(set(entries)) != 1:
                raise ValueError(
                    "Local LLM configuration contains multiple Logos entries "
                    f"for {model}"
                )
            configured[str(LOGOS_CANDIDATES[model]["model_env"])] = model
    os.environ.update(configured)
    metadata = {
        "endpoint": endpoint or None,
        "apiVersion": api_version or None,
    }
    if logos_entries:
        metadata["logosBaseUrl"] = configured["IRIS_QA_LOGOS_BASE_URL"]
    return metadata


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


def _validate_logos_base_url(value: str) -> None:
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("Logos base URL has an invalid port") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname != "logos.aet.cit.tum.de"
        or port not in {None, 443}
        or parsed.path.rstrip("/") != "/v1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Logos base URL must be https://logos.aet.cit.tum.de/v1")


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
    reasoning_effort: str | None = "medium",
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
        "reasoning_effort_values": ["none", "low", "medium", "high", "xhigh"],
        "use_responses_api": True,
        "cost_per_million_input_token": float(input_rate),
        "cost_per_million_output_token": float(output_rate),
    }
    if reasoning_effort is not None:
        entry["reasoning_effort"] = reasoning_effort
    if auth_mode == "api_key":
        if not api_key:
            raise ValueError("API-key model configuration requires a local key")
        # The current origin/main schema requires this field. The containing
        # config is a mode-600 temporary file removed when the worker exits.
        entry["api_key"] = api_key  # pragma: allowlist secret
    return entry


def _logos_model(
    *,
    model_id: str,
    model: str,
    rate,
    api_key: str,
    reasoning_effort: str | None,
) -> dict:
    base_url = _required("IRIS_QA_LOGOS_BASE_URL").rstrip("/")
    _validate_logos_base_url(base_url)
    if model not in LOGOS_CANDIDATES:
        raise ValueError(f"Unexpected Logos candidate model: {model}")
    candidate = LOGOS_CANDIDATES[model]
    entry = {
        "id": model_id,
        "type": "openai_chat",
        "model": model,
        "base_url": base_url,
        "api_key": api_key,  # pragma: allowlist secret
        "use_responses_api": candidate["use_responses_api"],
        "cost_per_million_input_token": float(rate.input_per_million),
        "cost_per_million_output_token": float(rate.output_per_million),
    }
    if reasoning_effort is not None:
        entry.update(
            {
                "supports_temperature": False,
                "supports_reasoning_effort": True,
                "reasoning_effort": reasoning_effort,
                "reasoning_effort_values": [
                    "none",
                    "low",
                    "medium",
                    "high",
                    "xhigh",
                ],
            }
        )
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


def _logos_candidate(candidate_model: str) -> tuple[str, str | None] | None:
    """Return the Logos model and reasoning effort of a candidate, if it is one."""
    if candidate_model in LOGOS_CANDIDATE_VARIANTS:
        return LOGOS_CANDIDATE_VARIANTS[candidate_model]
    if candidate_model in LOGOS_CANDIDATES:
        return candidate_model, LOGOS_CANDIDATES[candidate_model]["reasoning_effort"]
    return None


def _logos_helper_model(rate, api_key: str) -> dict:
    """The model Iris calls for its own side tasks, served by Logos instead of Azure."""
    base_url = _required("IRIS_QA_LOGOS_BASE_URL").rstrip("/")
    _validate_logos_base_url(base_url)
    return {
        "id": "qa-aux-mini",
        "type": "openai_chat",
        "model": LOGOS_HELPER_MODEL,
        "base_url": base_url,
        "api_key": api_key,  # pragma: allowlist secret
        "use_responses_api": False,
        "supports_temperature": False,
        "supports_reasoning_effort": True,
        "reasoning_effort": "none",
        "reasoning_effort_values": ["none", "low", "medium", "high", "xhigh"],
        "cost_per_million_input_token": float(rate.input_per_million),
        "cost_per_million_output_token": float(rate.output_per_million),
    }


def create_worker_configuration(
    rate_card, candidate_model: str, *, skip_judge: bool = False
) -> WorkerConfiguration:
    if candidate_model not in CANDIDATE_MODEL_IDS:
        raise ValueError(f"Unsupported QA candidate model: {candidate_model}")
    logos_candidate = _logos_candidate(candidate_model)
    helper_via_logos = os.environ.get(HELPER_ROUTE_ENV) == "logos"
    rates = {rate.model: rate for rate in (*rate_card.candidates, rate_card.judge)}
    models: list[dict] = []
    if helper_via_logos:
        if not skip_judge:
            raise ValueError("A Logos-only configuration needs the judge to be skipped")
        if logos_candidate is None:
            raise ValueError(
                "A Logos-only configuration can only run Logos candidates; "
                f"{candidate_model} needs an Azure deployment"
            )
    else:
        endpoint = _azure_endpoint()
        auth_mode = os.environ.get("IRIS_QA_AZURE_AUTH_MODE", "azure_ad")
        if auth_mode not in {"azure_ad", "api_key"}:
            raise ValueError("IRIS_QA_AZURE_AUTH_MODE must be azure_ad or api_key")
        if auth_mode == "api_key":
            _required("IRIS_QA_AZURE_API_KEY")

        deployments = {"gpt-5.4-mini": _required("IRIS_QA_GPT_54_MINI_DEPLOYMENT")}
        if not skip_judge:
            deployments["gpt-5.4"] = _required("IRIS_QA_JUDGE_DEPLOYMENT")
        if candidate_model != "gpt-5.4-mini" and logos_candidate is None:
            deployments[candidate_model] = _required(
                CANDIDATE_DEPLOYMENT_ENV[candidate_model]
            )
        if len(set(deployments.values())) != len(deployments):
            raise ValueError(
                "Candidate, auxiliary, and judge deployments must be distinct"
            )
        api_version = os.environ.get(
            "IRIS_QA_AZURE_API_VERSION", "2025-04-01-preview"
        ).strip()
        if not api_version:
            raise ValueError("IRIS_QA_AZURE_API_VERSION must not be empty")
        local_api_key = os.environ.get("IRIS_QA_AZURE_API_KEY")
        models = [
            _model(
                model_id=CANDIDATE_MODEL_IDS.get(model, "qa-judge"),
                model=model,
                deployment=deployment,
                endpoint=endpoint,
                api_version=api_version,
                auth_mode=auth_mode,
                input_rate=str(rates[model].input_per_million),
                output_rate=str(rates[model].output_per_million),
                reasoning_effort=(
                    None if model in DEFAULT_REASONING_MODELS else "medium"
                ),
                api_key=local_api_key if auth_mode == "api_key" else None,
            )
            for model, deployment in deployments.items()
        ]
    if logos_candidate is not None:
        base_model, reasoning_effort = logos_candidate
        logos_model = _required(str(LOGOS_CANDIDATES[base_model]["model_env"]))
        logos_key = _required("IRIS_QA_LOGOS_API_KEY")
        models.append(
            _logos_model(
                model_id=CANDIDATE_MODEL_IDS[candidate_model],
                model=logos_model,
                rate=rates[candidate_model],
                api_key=logos_key,
                reasoning_effort=reasoning_effort,
            )
        )
    mini_rate = rates["gpt-5.4-mini"]
    if helper_via_logos:
        models.append(
            _logos_helper_model(mini_rate, _required("IRIS_QA_LOGOS_API_KEY"))
        )
    else:
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
    candidate_id = CANDIDATE_MODEL_IDS[candidate_model]
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
        IRIS_QA_JUDGE_MODEL=rate_card.judge.model,
    )
    return WorkerConfiguration(directory, environment)

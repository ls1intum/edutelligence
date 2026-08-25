import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Union

import yaml
from starlette.requests import Request

from logos.dbutils.dbmanager import DBManager, get_unique_models_from_deployments
from logos.dbutils.types import infer_cloud_provider_type, normalize_provider_type

logger = logging.getLogger(__name__)


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host


def _extract_text_from_content(content: Union[str, List[Dict[str, Any]]]) -> str:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: List[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") != "text":
                continue
            txt = part.get("text")
            if isinstance(txt, str):
                parts.append(txt)
        return "\n".join(parts)
    return ""


def extract_prompt(json_data: Dict[str, Any]) -> Dict[str, str]:
    messages: List[Dict[str, Any]] = []
    if "input_payload" in json_data and "messages" in json_data["input_payload"]:
        messages = json_data["input_payload"]["messages"]
    elif "messages" in json_data:
        messages = json_data["messages"]

    last_by_role: Dict[str, Dict[str, Any]] = {}

    for msg in messages:
        if not isinstance(msg, dict):
            continue

        role = str(msg.get("role", "")).lower()
        if role not in {"system", "user"}:
            continue

        last_by_role[role] = msg

    system_text = ""
    user_text = ""

    if "system" in last_by_role:
        system_text = _extract_text_from_content(last_by_role["system"].get("content", ""))

    if "user" in last_by_role:
        user_text = _extract_text_from_content(last_by_role["user"].get("content", ""))

    return {"system": system_text, "user": user_text}


def merge_url(base_url: str, endpoint: str) -> str:
    """
    Merge a base URL and an endpoint path.
    Example: merge_url("http://example.com", "/api/v1") -> "http://example.com/api/v1"
    """
    if endpoint.startswith("http"):
        return endpoint
    base = base_url.rstrip("/")
    path = endpoint.lstrip("/")
    return f"{base}/{path}"


def extract_model(json_data: dict) -> str:
    """Extract model name from request body (supports OpenAI and gRPC formats)."""
    if "model" in json_data:
        return json_data["model"]
    # gRPC
    elif "input_payload" in json_data and "model" in json_data["input_payload"]:
        return json_data["input_payload"]["model"]
    return ""


def parse_provider_config(name: str) -> dict:
    """Load provider configuration from YAML file."""
    try:
        cwd_path = Path.cwd() / "config" / f"config-{name}.yaml"
        repo_path = Path(__file__).resolve().parents[3] / "config" / f"config-{name}.yaml"
        for candidate in (cwd_path, repo_path):
            if candidate.exists():
                with candidate.open() as stream:
                    return yaml.safe_load(stream)
    except (FileNotFoundError, yaml.YAMLError):
        pass

    logging.warning(
        "parse_provider_config: missing config for %s (cwd=%s); using default openwebui config",
        name,
        Path.cwd(),
    )
    # Fallback to default openwebui config
    return {
        "provider": "openwebui",
        "forward_url": "{base_url}/{path}",
        "required_headers": ["Authorization"],
        "auth": {"header": "Authorization", "format": "{Authorization}"},
    }


def request_setup(headers: dict, api_key_id: int, db: "DBManager | None" = None):
    """
    Get available models for the user and normalize provider types.

    Pass an already-open `db` to reuse the caller's session/connection
    instead of checking out a new one from the pool.
    """
    if db is not None:
        raw_deployments = db.get_deployments_for_api_key(api_key_id)
    else:
        with DBManager() as owned_db:
            raw_deployments = owned_db.get_deployments_for_api_key(api_key_id)

    deployments = []
    for deployment in raw_deployments:
        d = dict(deployment)
        if d.get("provider_id"):
            provider_type = normalize_provider_type(d.get("type"))
            cloud_provider_type = d.get("cloud_provider_type") or infer_cloud_provider_type(
                d.get("type"), base_url=d.get("base_url")
            )
            d["type"] = "azure" if provider_type == "cloud" and cloud_provider_type == "azure" else provider_type
        deployments.append(d)

    allowed_models = get_unique_models_from_deployments(deployments)
    return deployments, allowed_models


def proxy_behaviour(headers: dict, providers: list, path: str):
    """
    Handle proxy mode: forward request directly to provider without classification.
    Returns (proxy_headers, forward_url, provider_id) or error dict.
    """
    proxy_headers = None
    forward_url = None
    provider_info = None

    def _provider_label(item: object) -> str:
        if isinstance(item, dict):
            return item.get("name", str(item))
        return str(item)

    for provider in providers:
        with DBManager() as db:
            provider_info = db.get_provider(provider)

        if "azure" in provider_info["name"].lower():
            config = parse_provider_config("azure")
        elif "openwebui" in provider_info["name"].lower():
            config = parse_provider_config("openwebui")
        elif (
            "openai" in provider_info["name"].lower()
            and "Authorization" in headers
            and "sk-" in headers["Authorization"]
        ):
            config = parse_provider_config("openai")
        else:
            logging.debug(
                "proxy_behaviour: skipping provider %s (name=%s) no matching handler",
                provider_info.get("id"),
                provider_info.get("name"),
            )
            continue

        req_headers = config["required_headers"]
        logging.debug(
            "proxy_behaviour: required headers for %s (%s) -> %s",
            provider_info.get("id"),
            provider_info.get("name"),
            req_headers,
        )
        check = True
        for req_header in req_headers:
            if req_header not in headers:
                logging.warning(
                    "proxy_behaviour: missing required header '%s' for provider %s (%s)",
                    req_header,
                    provider_info.get("id"),
                    provider_info.get("name"),
                )
                check = False
                break
        if not check:
            continue

        req_headers = {i: headers[i] for i in req_headers}
        req_headers["base_url"] = provider_info["base_url"]
        req_headers["path"] = path

        forward_url = config["forward_url"].format(**req_headers)
        forward_url = forward_url[:8] + forward_url[8:].replace("//", "/")

        proxy_headers = {
            config["auth"]["header"]: config["auth"]["format"].format(**req_headers),
            "Content-Type": "application/json",
        }
        break  # Found a suitable provider

    if proxy_headers is None:
        logging.error(
            "proxy_behaviour: no suitable provider found for path=%s headers=%s providers=%s",
            path,
            list(headers.keys()),
            ([_provider_label(p) for p in providers] if isinstance(providers, list) else _provider_label(providers)),
        )
        return {
            "error": "Could not identify suitable provider. Please check your headers and registered provider names"
        }, 500
    return proxy_headers, forward_url, int(provider_info["id"])


# The Responses API reports usage as input/output tokens; billing, rate
# limiting, and token pricing are keyed to the Chat Completions names, so
# normalize on extraction.
_RESPONSES_USAGE_KEY_MAP = {
    "input_tokens": "prompt_tokens",
    "output_tokens": "completion_tokens",
}

# Nested details dicts, flattened under the canonical prefix: Chat Completions'
# prompt/completion_tokens_details and the Responses API's
# input/output_tokens_details (e.g. input_tokens_details.cached_tokens and
# prompt_tokens_details.cached_tokens both become prompt_cached_tokens).
_USAGE_DETAILS_PREFIXES = (
    ("prompt_tokens_details", "prompt_"),
    ("completion_tokens_details", "completion_"),
    ("input_tokens_details", "prompt_"),
    ("output_tokens_details", "completion_"),
)


def extract_token_usage(usage: dict) -> dict:
    """
    Extract detailed token usage from provider response, filtering out meta fields.
    Handles OpenAI Chat Completions, OpenAI Responses API, and Ollama formats.
    """
    usage_tokens = {}

    def _add(key: str, value: Any) -> None:
        if (
            key == "seconds"
            and not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
            and value >= 0
        ):
            # usage_tokens stores integers. Milliseconds retain fractional
            # transcription duration without requiring a schema change.
            usage_tokens["audio_milliseconds"] = math.ceil(float(value) * 1000)
            return
        # Only integer token counts are stored (one row per type in
        # usage_tokens). Skip non-numeric fields such as Azure's nested
        # `latency_checkpoint` dict, which would otherwise reach the DB as a
        # token_count and crash with "can't adapt type 'dict'". bool is an int
        # subclass but never a token count, so exclude it explicitly.
        if isinstance(value, bool) or not isinstance(value, int):
            return
        usage_tokens[key] = value

    for name in usage:
        if "tokens_details" in name:
            continue
        if (
            name
            in {
                "approximate_total",
                "eval_count",
                "eval_duration",
                "load_duration",
                "prompt_eval_count",
                "prompt_eval_duration",
                "prompt_token/s",
                "response_token/s",
                "total_duration",
            }
            or "/s" in name
        ):
            continue
        _add(_RESPONSES_USAGE_KEY_MAP.get(name, name), usage[name])

    # Flatten nested token details under the canonical prefix
    for details_key, prefix in _USAGE_DETAILS_PREFIXES:
        details = usage.get(details_key)
        if isinstance(details, dict):
            for name in details:
                _add(prefix + name, details[name])

    return usage_tokens

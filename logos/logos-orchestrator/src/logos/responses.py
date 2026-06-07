import logging
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


def request_setup(headers: dict, api_key_id: int):
    """
    Get available models for the user and normalize provider types.
    """
    with DBManager() as db:
        raw_deployments = db.get_deployments_for_api_key(api_key_id)

        deployments = []
        for deployment in raw_deployments:
            d = dict(deployment)
            p_id = d.get("provider_id")
            if p_id:
                p_info = db.get_provider(p_id) or {}
                provider_type = normalize_provider_type(d.get("type"))
                cloud_provider_type = p_info.get("cloud_provider_type") or infer_cloud_provider_type(
                    d.get("type"), base_url=p_info.get("base_url")
                )
                d["type"] = cloud_provider_type if cloud_provider_type else provider_type
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


def extract_token_usage(usage: dict) -> dict:
    """
    Extract detailed token usage from provider response, filtering out meta fields.
    Handles both OpenAI and Ollama formats.
    """
    usage_tokens = {}
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
        usage_tokens[name] = usage[name]

    # Extract prompt token details
    prompt_details = usage.get("prompt_tokens_details")
    if isinstance(prompt_details, dict):
        for name in prompt_details:
            usage_tokens["prompt_" + name] = prompt_details[name]

    # Extract completion token details
    completion_details = usage.get("completion_tokens_details")
    if isinstance(completion_details, dict):
        for name in completion_details:
            usage_tokens["completion_" + name] = completion_details[name]

    return usage_tokens

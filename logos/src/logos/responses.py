import datetime
import json
import logging
import time
from typing import Union, List, Dict, Any, Optional

from fastapi.responses import StreamingResponse
import httpx
import yaml
from pathlib import Path
from starlette.requests import Request

from logos.dbutils.dbmanager import DBManager


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
        'provider': 'openwebui',
        'forward_url': '{base_url}/{path}',
        'required_headers': ['Authorization'],
        'auth': {'header': 'Authorization', 'format': '{Authorization}'}
    }


def request_setup(headers: dict, logos_key: str, profile_id: Optional[int] = None):
    """
    Get available models for the user.

    Args:
        headers: Request headers
        logos_key: User's authentication key
        profile_id: If provided, filter to this profile only (REQUIRED for v1/openai/jobs endpoints)

    Returns:
        List of model IDs (may be empty if no models available)

    Raises:
        PermissionError: If user lacks permission to access models
        ValueError: If profile ID is invalid
    """
    with DBManager() as db:
        # Get available models for this key
        if profile_id is not None:
            # Explicit profile-based filtering (new preferred path)
            models = db.get_models_by_profile(logos_key, profile_id)
        else:
            # Fallback: all models for key (for admin endpoints that don't need profile isolation)
            models = db.get_models_with_key(logos_key)

    if not models:
        return list()
    else:
        # Return ids of all available models
        logging.info(f"Found models {models} for classification")
        return models


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
        elif "openai" in provider_info["name"].lower() and "Authorization" in headers and "sk-" in headers["Authorization"]:
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
            "Content-Type": "application/json"
        }
        break  # Found a suitable provider

    if proxy_headers is None:
        logging.error(
            "proxy_behaviour: no suitable provider found for path=%s headers=%s providers=%s",
            path,
            list(headers.keys()),
            [_provider_label(p) for p in providers] if isinstance(providers, list) else _provider_label(providers),
        )
        return {"error": "Could not identify suitable provider. Please check your headers and registered provider names"}, 500
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
        if name in {"approximate_total", "eval_count", "eval_duration", "load_duration",
                    "prompt_eval_count", "prompt_eval_duration", "prompt_token/s", "response_token/s",
                    "total_duration"} or "/s" in name:
            continue
        usage_tokens[name] = usage[name]

    # Extract prompt token details
    if "prompt_tokens_details" in usage:
        for name in usage["prompt_tokens_details"]:
            usage_tokens["prompt_" + name] = usage["prompt_tokens_details"][name]

    # Extract completion token details
    if "completion_tokens_details" in usage:
        for name in usage["completion_tokens_details"]:
            usage_tokens["completion_" + name] = usage["completion_tokens_details"][name]

    return usage_tokens

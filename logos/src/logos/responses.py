import datetime
import json
import logging
import time
from typing import Union, List, Dict, Any, Optional

from fastapi.responses import StreamingResponse
import httpx
import yaml
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
        with open(f"./config/config-{name}.yaml") as stream:
            return yaml.safe_load(stream)
    except (FileNotFoundError, yaml.YAMLError):
        # Fallback to default openwebui config
        return {
            'provider': 'openwebui',
            'forward_url': '{base_url}/{path}',
            'required_headers': ['Authorization'],
            'auth': {'header': 'Authorization', 'format': '{Authorization}'}
        }


def request_setup(headers: dict, logos_key: str):
    """
    Determine if Logos should run in proxy mode or resource mode.
    Returns empty list for proxy mode, or list of model IDs for resource mode.
    """
    try:
        with DBManager() as db:
            # Get available models for this key
            if "use_profile" in headers:
                models = db.get_models_by_profile(logos_key, int(headers["use_profile"]))
            else:
                models = db.get_models_with_key(logos_key)
        if not models or "proxy" in headers:
            return list()
        else:
            # Return ids of all available models
            logging.info(f"Found models {models} for classification")
            return models
    except PermissionError as e:
        return {"error": str(e)}, 401
    except ValueError as e:
        return {"error": str(e)}, 401


def proxy_behaviour(headers: dict, providers: list, path: str):
    """
    Handle proxy mode: forward request directly to provider without classification.
    Returns (proxy_headers, forward_url, provider_id) or error dict.
    """
    proxy_headers = None
    forward_url = None
    provider_info = None

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
            continue

        req_headers = config["required_headers"]
        check = True
        for req_header in req_headers:
            if req_header not in headers:
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


def get_streaming_response(forward_url: str, proxy_headers: dict, json_data: dict,
                           log_id: Optional[int], provider_id: int, model_id: Optional[int],
                           policy_id: int, classified: dict):
    """
    Handle streaming response for proxy mode.
    Directly forwards to provider using HTTPX (no executor).
    """
    json_data = json_data.copy()
    json_data["stream"] = True
    json_data["stream_options"] = {"include_usage": True}

    full_text = ""
    response: Union[None, dict] = None
    first_response = None
    ttft = None

    async def streamer():
        nonlocal full_text, response, first_response, ttft
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", forward_url, headers=proxy_headers, json=json_data) as resp:
                    async for raw_line in resp.aiter_lines():
                        if not raw_line:
                            continue
                        if raw_line.startswith("data: "):
                            if ttft is None:
                                ttft = datetime.datetime.now(datetime.timezone.utc)
                                if log_id:
                                    with DBManager() as db:
                                        db.set_time_at_first_token(log_id)
                            payload = raw_line.removeprefix("data: ").strip()
                            if payload == "[DONE]":
                                break
                            try:
                                blob = json.loads(payload)
                                response = blob
                                if "choices" in blob and blob["choices"] and "delta" in blob["choices"][0] and "content" in blob["choices"][0]["delta"]:
                                    content = blob["choices"][0]["delta"]["content"]
                                    if first_response is None:
                                        first_response = blob
                                    if content:
                                        full_text += content
                            except:
                                pass
                        yield (raw_line + "\n").encode()
        finally:
            after_streaming()

    def after_streaming():
        if log_id is None:
            return

        with DBManager() as db:
            nonlocal response, ttft, first_response
            if first_response is not None:
                usage = response.get("usage", {}) if response is not None else {}
                first_response["choices"][0]["delta"]["content"] = full_text
                usage_tokens = extract_token_usage(usage)
                if response:
                    first_response["usage"] = response.get("usage")
            else:
                response = {"content": full_text}
                first_response = {"content": full_text}
                usage_tokens = {}

            if ttft is None:
                db.set_time_at_first_token(log_id)
            db.set_response_payload(log_id, first_response, provider_id, model_id, usage_tokens, policy_id, classified)

    return StreamingResponse(streamer(), media_type="application/json")


async def get_standard_response(forward_url: str, proxy_headers: dict, json_data: dict,
                                log_id: Optional[int], provider_id: int, model_id: Optional[int],
                                policy_id: int, classified: dict):
    """
    Handle synchronous response for proxy mode.
    Directly forwards to provider using HTTPX (no executor).
    """
    async with httpx.AsyncClient() as client:
        resp = await client.request(
            method="POST",
            url=forward_url,
            json=json_data,
            headers=proxy_headers,
            timeout=30,
        )

    try:
        response: dict = resp.json()
    except:
        response: dict = {"error": resp.text}

    if log_id is not None:
        usage = response.get("usage", {})
        usage_tokens = extract_token_usage(usage)

        with DBManager() as db:
            db.set_time_at_first_token(log_id)
            db.set_response_timestamp(log_id)
            db.set_response_payload(log_id, response, provider_id, model_id, usage_tokens, policy_id, classified)

    return response

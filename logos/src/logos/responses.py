import datetime
import json
import logging
import time
from typing import Union, List, Dict, Any

from starlette.requests import Request


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

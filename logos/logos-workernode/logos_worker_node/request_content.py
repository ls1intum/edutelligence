"""Decode multipart inference payloads received from the Logos orchestrator."""

import base64
import binascii
from typing import Any

MULTIPART_PAYLOAD_KEY = "_logos_multipart"


def httpx_request_parts(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Return httpx request kwargs and safe upstream headers for a payload."""
    multipart = payload.get(MULTIPART_PAYLOAD_KEY)
    if not isinstance(multipart, dict):
        return {"json": payload}, {"Content-Type": "application/json"}

    data = [(str(name), str(value)) for name, value in multipart.get("fields", [])]
    files: list[tuple[str, tuple]] = []
    for item in multipart.get("files", []):
        try:
            content = base64.b64decode(item["content_base64"], validate=True)
        except (KeyError, ValueError, binascii.Error) as exc:
            raise ValueError("Invalid encoded multipart file") from exc
        files.append(
            (
                str(item.get("field_name") or "file"),
                (
                    str(item.get("filename") or "audio"),
                    content,
                    str(item.get("content_type") or "application/octet-stream"),
                ),
            )
        )
    form_parts = [(name, (None, value)) for name, value in data]
    return {"files": [*form_parts, *files]}, {}

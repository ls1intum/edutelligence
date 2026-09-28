"""Payload builders shared by fake vLLM HTTP servers."""

from __future__ import annotations

from typing import Any, Optional


def models_payload(
    model: str,
    *,
    owned_by: str,
    created: int,
    max_model_len: Optional[int] = None,
) -> dict[str, Any]:
    """Build the OpenAI-compatible model-list response."""
    model_entry: dict[str, Any] = {
        "id": model,
        "object": "model",
        "created": created,
        "owned_by": owned_by,
    }
    if max_model_len is not None:
        model_entry.update({"root": model, "max_model_len": max_model_len})
    return {"object": "list", "data": [model_entry]}


def chat_completion_payload(
    model: str,
    text: str,
    *,
    request_id: str,
    created: int,
    prompt_tokens: int,
    completion_tokens: int,
    prompt_tokens_details: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build a deterministic non-streaming chat-completion response."""
    usage: dict[str, Any] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    if prompt_tokens_details is not None:
        usage["prompt_tokens_details"] = prompt_tokens_details
    return {
        "id": request_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
    }

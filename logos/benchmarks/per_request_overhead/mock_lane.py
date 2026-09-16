"""Mock vLLM lane for the per-request overhead benchmark.

Serves the endpoints the worker's LaneManager probes and relays to, with
fixed (deterministic) responses so measured latency is dominated by the
Logos forwarding path rather than generation:

- ``GET /health``                     → 200 {}
- ``GET /v1/models``                  → fixed model list (LaneManager liveness probe)
- ``GET /metrics``                    → Prometheus text; token counters *do*
                                         increase per request so the worker's
                                         stuck-lane detection stays quiet
- ``GET /is_sleeping``                → {"is_sleeping": false}
- ``POST /v1/chat/completions``       → fixed ~1.5 KB OpenAI response with a
                                         stable ``usage`` block (3 token types:
                                         prompt/completion/total)

Run: ``uvicorn mock_lane:app --host 127.0.0.1 --port <lane-port> --no-access-log``
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict

from fastapi import FastAPI
from pydantic import BaseModel

MODEL_NAME = os.environ.get("LOGOS_BENCH_MODEL", "bench-local-model")

app = FastAPI()

# Deterministic completion content sized to a realistic ~1.5 KB JSON body.
_FILLER = "The quick brown fox jumps over the lazy dog. " * 28  # ≈1.5 KB
_USAGE = {"prompt_tokens": 12, "completion_tokens": 300, "total_tokens": 312}

# Metrics counters (incremented per request — stuck-lane detection compares them).
_prompt_tokens_total = 0
_completion_tokens_total = 0
_start = time.monotonic()


class _ChatRequest(BaseModel):
    model: str = ""
    messages: list = []
    stream: bool = False


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {}


@app.get("/v1/models")
async def models() -> Dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_NAME,
                "object": "model",
                "created": 1700000000,
                "owned_by": "bench",
            }
        ],
    }


@app.get("/is_sleeping")
async def is_sleeping() -> Dict[str, Any]:
    return {"is_sleeping": False}


@app.get("/metrics")
async def metrics() -> str:
    lines = [
        "# HELP vllm:num_requests_running Number of requests currently running.",
        "# TYPE vllm:num_requests_running gauge",
        "vllm:num_requests_running 0",
        "# HELP vllm:prompt_tokens_total Total number of prompt tokens processed.",
        "# TYPE vllm:prompt_tokens_total counter",
        f"vllm:prompt_tokens_total {_prompt_tokens_total}",
        "# HELP vllm:generation_tokens_total Total number of generation tokens processed.",
        "# TYPE vllm:generation_tokens_total counter",
        f"vllm:generation_tokens_total {_completion_tokens_total}",
        "# HELP vllm:time_to_first_token_seconds Time to first token.",
        "# TYPE vllm:time_to_first_token_seconds histogram",
    ]
    return "\n".join(lines) + "\n"


@app.post("/v1/chat/completions")
async def chat_completions(req: _ChatRequest) -> Dict[str, Any]:
    global _prompt_tokens_total, _completion_tokens_total
    _prompt_tokens_total += _USAGE["prompt_tokens"]
    _completion_tokens_total += _USAGE["completion_tokens"]
    return {
        "id": f"chatcmpl-bench-{_prompt_tokens_total}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model or MODEL_NAME,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": _FILLER},
                "finish_reason": "stop",
            }
        ],
        "usage": dict(_USAGE),
    }


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("LOGOS_BENCH_LANE_PORT", "11436")), log_level="warning")

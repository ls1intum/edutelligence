"""Fake cloud provider for the gateway concurrency benchmark.

Serves an OpenAI-shaped ``/v1/chat/completions`` (streaming and non-streaming)
with a configurable per-token delay, so the benchmark measures the gateway's
own concurrency ceiling and added latency rather than a real cloud provider's
throttling. The gateway's ``CloudForwardUrlBuilder`` forwards to
``base_url + inbound path`` when a provider has no per-model absolute
endpoint (see ``seed.sql``), so this only has to answer plain
``POST /v1/chat/completions`` — no Azure deployment-path emulation needed.

Run: ``uvicorn fake_cloud_upstream:app --host 0.0.0.0 --port <port> --no-access-log``

Environment (all optional):
  LOGOS_BENCH_GW_MODEL            (bench-cloud-model)
  LOGOS_BENCH_GW_TOKEN_COUNT      (40)   tokens streamed per completion
  LOGOS_BENCH_GW_TOKEN_DELAY_MS   (30)   delay between streamed tokens
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, AsyncIterator, Dict

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

_E2E = Path(__file__).resolve().parents[2] / "e2e"
if str(_E2E) not in sys.path:
    sys.path.insert(0, str(_E2E))

from harness.fake_vllm.protocol import chat_completion_payload, models_payload  # noqa: E402

MODEL_NAME = os.environ.get("LOGOS_BENCH_GW_MODEL", "bench-cloud-model")
TOKEN_COUNT = int(os.environ.get("LOGOS_BENCH_GW_TOKEN_COUNT", "40"))
TOKEN_DELAY_S = int(os.environ.get("LOGOS_BENCH_GW_TOKEN_DELAY_MS", "30")) / 1000.0

app = FastAPI()

_FILLER_WORD = "token "
_seq = 0


class _ChatRequest(BaseModel):
    model: str = ""
    messages: list = []
    stream: bool = False


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {}


@app.get("/v1/models")
async def models() -> Dict[str, Any]:
    return models_payload(MODEL_NAME, owned_by="bench", created=1700000000)


async def _sse_chunks(model: str, request_id: str) -> AsyncIterator[str]:
    created = int(time.time())
    # Role-opening chunk, matching real OpenAI/Azure streaming shape.
    yield "data: " + json.dumps(
        {
            "id": request_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        }
    ) + "\n\n"
    for _ in range(TOKEN_COUNT):
        if TOKEN_DELAY_S > 0:
            await asyncio.sleep(TOKEN_DELAY_S)
        yield "data: " + json.dumps(
            {
                "id": request_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {"content": _FILLER_WORD}, "finish_reason": None}],
            }
        ) + "\n\n"
    yield "data: " + json.dumps(
        {
            "id": request_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
    ) + "\n\n"
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(req: _ChatRequest):
    global _seq
    _seq += 1
    request_id = f"chatcmpl-bench-gw-{_seq}"
    model = req.model or MODEL_NAME
    if req.stream:
        return StreamingResponse(_sse_chunks(model, request_id), media_type="text/event-stream")
    if TOKEN_DELAY_S > 0:
        await asyncio.sleep(TOKEN_DELAY_S * TOKEN_COUNT)
    text = (_FILLER_WORD * TOKEN_COUNT).strip()
    return chat_completion_payload(
        model,
        text,
        request_id=request_id,
        created=int(time.time()),
        prompt_tokens=12,
        completion_tokens=TOKEN_COUNT,
    )


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("LOGOS_BENCH_GW_UPSTREAM_PORT", "9100")),
        log_level="warning",
    )

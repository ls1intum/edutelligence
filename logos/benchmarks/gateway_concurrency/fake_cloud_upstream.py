"""Fake cloud provider for the gateway concurrency benchmark.

Serves an OpenAI-shaped ``/v1/chat/completions`` (streaming and non-streaming)
with a configurable per-token delay, so the benchmark measures the gateway's
own concurrency ceiling and added latency rather than a real cloud provider's
throttling. The gateway's ``CloudForwardUrlBuilder`` forwards to
``base_url + inbound path`` when a provider has no per-model absolute
endpoint (see ``seed.sql``), so this only has to answer plain
``POST /v1/chat/completions`` — no Azure deployment-path emulation needed.

It also carries the concurrency leg's measurement point. A gateway
streaming task stays alive for exactly as long as it is relaying one of
these responses, so the number of completions in flight *here* is the
number of gateway relay slots occupied. A client cannot observe that: the
gateway can push a small response into the socket buffers and free its
slot while the client is still reading. ``/_bench/*`` therefore arms a
server-side barrier that pins every completion open until a whole step is
being relayed, and reports the peak overlap it saw.

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
from typing import Any, AsyncIterator, Dict, Optional

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


class _StepGate:
    """Server-side barrier and overlap counter for one concurrency step.

    ``active`` rises when a completion starts being relayed and falls when
    it ends, so ``peak`` is the largest number of gateway relay tasks alive
    at the same moment — the capacity number the ramp is after. Disarmed
    (``target`` 0) it only counts, which is what the latency and failover
    legs want.

    ``released_at`` is wall clock rather than a monotonic reading because
    the load generator subtracts the barrier from its own latency samples
    and runs in a different process on the same host.
    """

    def __init__(self) -> None:
        self.target = 0
        self.hold_timeout_s = 30.0
        self.active = 0
        self.peak = 0
        self.admitted = 0
        self.timed_out = False
        self.released_at: Optional[float] = None
        self._gate = asyncio.Event()
        self._gate.set()

    def arm(self, target: int, hold_timeout_s: float) -> None:
        self.target = max(0, target)
        self.hold_timeout_s = hold_timeout_s
        self.active = 0
        self.peak = 0
        self.admitted = 0
        self.timed_out = False
        self.released_at = None
        self._gate = asyncio.Event()
        if self.target <= 0:
            self._release()

    def _release(self) -> None:
        if self.released_at is None:
            self.released_at = time.time()
        self._gate.set()

    async def enter(self) -> None:
        self.active += 1
        self.admitted += 1
        self.peak = max(self.peak, self.active)
        if self.target and self.admitted >= self.target:
            self._release()
        if self._gate.is_set():
            return
        try:
            await asyncio.wait_for(self._gate.wait(), timeout=self.hold_timeout_s)
        except asyncio.TimeoutError:
            # The step never reached its target, which *is* the ceiling.
            # Release rather than sit here until the gateway's own upstream
            # read timeout turns a measurement into an outage.
            self.timed_out = True
            self._release()

    def leave(self) -> None:
        self.active -= 1

    def stats(self) -> Dict[str, Any]:
        return {
            "target": self.target,
            "peak_concurrent_relays": self.peak,
            "admitted": self.admitted,
            "active": self.active,
            "timed_out": self.timed_out,
            "released_at": self.released_at,
            "hold_timeout_s": self.hold_timeout_s,
        }


_gate = _StepGate()


async def _held_open(inner: AsyncIterator[str]) -> AsyncIterator[str]:
    """Relay ``inner``, pausing once the first chunk is out.

    Pausing after the first chunk and not before it keeps the client's TTFB
    a measurement of the gateway's admission latency; everything after it is
    the barrier, which the load generator subtracts using ``released_at``.
    """
    entered = False
    try:
        async for chunk in inner:
            yield chunk
            if not entered:
                entered = True
                await _gate.enter()
    finally:
        if entered:
            _gate.leave()


class _ChatRequest(BaseModel):
    model: str = ""
    messages: list = []
    stream: bool = False


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {}


class _StepArm(BaseModel):
    target: int = 0
    hold_timeout_s: float = 30.0


@app.post("/_bench/step")
async def bench_arm_step(req: _StepArm) -> Dict[str, Any]:
    """Arm the barrier for the next step. Not part of the OpenAI surface."""
    _gate.arm(req.target, req.hold_timeout_s)
    return _gate.stats()


@app.get("/_bench/stats")
async def bench_stats() -> Dict[str, Any]:
    return _gate.stats()


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
        return StreamingResponse(_held_open(_sse_chunks(model, request_id)), media_type="text/event-stream")
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

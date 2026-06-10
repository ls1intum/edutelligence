"""Mock OpenAI-compatible SSE upstream with a fixed chunk cadence.

Emits one content chunk every --interval seconds for --duration seconds,
so any deviation in chunk arrival observed by stream_gap_probe.py is
attributable to the proxy, not the backend.

Usage:
    python tests/performance/mock_sse_upstream.py --port 9999 --interval 0.2
Register it in Logos as an OpenAI-type provider with base_url http://host:9999.
"""

import argparse
import asyncio
import json

from aiohttp import web


async def chat_completions(request: web.Request) -> web.StreamResponse:
    interval = request.app["interval"]
    duration = request.app["duration"]
    response = web.StreamResponse(
        status=200,
        headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"},
    )
    await response.prepare(request)

    total_chunks = max(1, int(duration / interval))
    for i in range(total_chunks):
        chunk = {
            "id": "mock-1",
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {"content": f"tok{i} "}, "finish_reason": None}],
        }
        await response.write(f"data: {json.dumps(chunk)}\n\n".encode())
        await asyncio.sleep(interval)

    usage_chunk = {
        "id": "mock-1",
        "object": "chat.completion.chunk",
        "choices": [],
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": total_chunks,
            "total_tokens": total_chunks + 1,
        },
    }
    await response.write(f"data: {json.dumps(usage_chunk)}\n\n".encode())
    await response.write(b"data: [DONE]\n\n")
    return response


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--interval", type=float, default=0.2, help="Seconds between chunks")
    parser.add_argument("--duration", type=float, default=60.0, help="Stream length in seconds")
    args = parser.parse_args()

    app = web.Application()
    app["interval"] = args.interval
    app["duration"] = args.duration
    app.router.add_post("/chat/completions", chat_completions)
    app.router.add_post("/v1/chat/completions", chat_completions)
    web.run_app(app, port=args.port)


if __name__ == "__main__":
    main()

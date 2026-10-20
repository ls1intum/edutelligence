"""Observe benchmark output without treating transport heartbeats as progress."""

import json

from logos.benchmarks.nightly import PROGRESS


def observe_response(response, job_id: int):
    """Track this attempt only; late responses cannot advance a newer attempt."""
    progress = PROGRESS.get(job_id)
    if progress is None or not progress.measuring or response.status_code != 200:
        return response
    iterator = getattr(response, "body_iterator", None)
    if iterator is None:
        try:
            data = json.loads(response.body)
            if data.get("choices") and not data.get("error"):
                progress.finish()
        except (ValueError, TypeError):
            pass
        return response

    async def measured_stream():
        buffer = ""
        finished = False
        failed = False
        completed = False
        terminal = False
        async for chunk in iterator:
            buffer += chunk.decode("utf-8", errors="replace") if isinstance(chunk, bytes) else chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                if not line.startswith("data:"):
                    continue
                if line[5:].strip() == "[DONE]":
                    terminal = True
                    continue
                try:
                    data = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if not isinstance(data, dict):
                    continue
                failed = failed or bool(data.get("error"))
                for choice in data.get("choices", []):
                    delta = choice.get("delta") or {}
                    if delta.get("content") or delta.get("reasoning_content") or delta.get("tool_calls"):
                        progress.output()
                    finished = finished or choice.get("finish_reason") is not None
            # Consumers can close the iterator as soon as they receive [DONE].
            # Record completion before handing that chunk to the consumer.
            if terminal and finished and not failed and not completed:
                progress.finish()
                completed = True
            yield chunk

    response.body_iterator = measured_stream()
    return response

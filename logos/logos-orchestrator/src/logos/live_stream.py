"""In-flight streaming state: the live view and the SSE log accumulator.

Two cooperating pieces, kept together because both exist only while a request
runs:

* ``_LiveStreamRegistry`` — the in-memory view of the requests streaming right
  now (token counts, generation rate), exposed through /internal/live_streams.
  A finished request's usage is in the database; one still running is nowhere
  but here, in the process the chunks pass through.

* ``_StreamingLogAccumulator`` — the line-buffered SSE parser that
  reconstructs text and usage from the chunks as they go past, so a request is
  logged (and live-reported) without buffering the whole body.

``_usage_tokens_from_payload`` turns a logged response payload into the token
counts the statistics and billing views read.
"""

import codecs
import copy
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from logos.billing.finalize import finalize_billing_inputs

# Anthropic Messages SSE event types the accumulator acts on. The stream also
# emits content_block_start/stop and ping, which carry neither text nor usage.
_MESSAGES_EVENT_TYPES = frozenset({"message_start", "message_delta", "message_stop", "content_block_delta"})

# Chat-completion delta keys that carry non-text structure (tool calls,
# function calls, audio). Their presence marks a stream a mid-flight resume
# must not attempt: a resume continues from the accumulated text only, so it
# would silently drop the structured part of the answer.
_STRUCTURED_DELTA_KEYS = ("tool_calls", "function_call", "audio")


class _LiveStreamRegistry:
    """Token counts of the requests running right now, keyed by request id.

    A finished request's usage is in the database; one still running is
    nowhere, and "nowhere" is what the statistics page showed for the whole
    minute a long generation takes. This holds the in-flight view, in memory
    and on the orchestrator, because that is the only process that sees the
    chunks go past.

    Bounded by construction: an entry exists only while its request is in
    flight and is dropped in the same ``finally`` that logs the completion.
    """

    def __init__(self, now: Any = time.time) -> None:
        self._streams: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        # Bumped on every mutation so a subscriber (the SSE stream) can tell
        # that something moved without diffing the whole table.
        self._version = 0
        # Injected rather than read off the module so a test can drive the clock
        # without patching time.time for everything else running in-process.
        self._now = now

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def start(
        self,
        request_id: Optional[str],
        model_name: Optional[str] = None,
        prompt_tokens: int = 0,
        prompt_estimated: bool = False,
    ) -> None:
        """Register a request as in-flight; non-destructive for known ids.

        A request is tracked from the moment it arrives, long before its
        response starts streaming: while it queues, the only figure available
        is the prompt estimate the context routing already computes. When the
        streamer later calls this with the model name, the entry must keep its
        counters and start time rather than resetting them — the numbers on
        the page would jump backwards.
        """
        if not request_id:
            return
        with self._lock:
            entry = self._streams.get(request_id)
            if entry is None:
                self._streams[request_id] = {
                    "model_name": model_name,
                    "started_at": self._now(),
                    # Set on the first delta, not here: the wait for a lane to warm
                    # up is not generation, and averaging over it would report a
                    # rate no one is seeing.
                    "first_token_at": None,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": 0,
                    # True until the upstream states the real prompt size; the
                    # page shows such a figure as an estimate, not a fact.
                    "prompt_estimated": prompt_estimated and prompt_tokens > 0,
                }
            else:
                if model_name:
                    entry["model_name"] = model_name
                if prompt_tokens > 0 and entry["prompt_tokens"] == 0:
                    entry["prompt_tokens"] = prompt_tokens
                    entry["prompt_estimated"] = prompt_estimated
            self._version += 1

    def update(self, request_id: Optional[str], tokens: Dict[str, int]) -> None:
        if not request_id:
            return
        with self._lock:
            entry = self._streams.get(request_id)
            if entry is None:
                return
            completion = tokens.get("completion_tokens", 0)
            if completion > 0 and entry["first_token_at"] is None:
                entry["first_token_at"] = self._now()
            prompt = tokens.get("prompt_tokens", 0)
            if prompt > 0:
                # The upstream has stated the prompt size; the estimate it
                # stood in for is no longer an estimate.
                entry["prompt_tokens"] = prompt
                entry["prompt_estimated"] = False
            entry["completion_tokens"] = completion
            self._version += 1

    def finish(self, request_id: Optional[str]) -> None:
        if not request_id:
            return
        with self._lock:
            if self._streams.pop(request_id, None) is not None:
                self._version += 1

    def snapshot(self) -> list[dict[str, Any]]:
        """Every running request, with the rate it is generating at."""
        now = self._now()
        out: list[dict[str, Any]] = []
        with self._lock:
            entries = [(rid, dict(entry)) for rid, entry in self._streams.items()]
        for request_id, entry in entries:
            first_token_at = entry["first_token_at"]
            completion = entry["completion_tokens"]
            elapsed = (now - first_token_at) if first_token_at else 0.0
            out.append(
                {
                    "request_id": request_id,
                    "model_name": entry["model_name"],
                    "prompt_tokens": entry["prompt_tokens"],
                    "prompt_estimated": entry["prompt_estimated"],
                    "completion_tokens": completion,
                    # Measured from the first token, so it is the generation
                    # rate rather than an average dragged down by queueing.
                    # None until there is a span to divide by.
                    "tokens_per_second": (completion / elapsed) if elapsed > 0.5 and completion > 0 else None,
                    "elapsed_seconds": now - entry["started_at"],
                }
            )
        return out


@dataclass
class _StreamingLogAccumulator:
    """
    Line-buffered SSE parser for request logging.

    Network chunk boundaries are not aligned with SSE event boundaries, especially on the
    logosnode websocket path. Buffer until complete lines are available so streamed usage
    metadata is not lost when it arrives split across chunks.
    """

    buffer: str = ""
    full_text: str = ""
    first_chunk: Optional[Dict[str, Any]] = None
    last_chunk: Optional[Dict[str, Any]] = None
    # Terminal Response object from a Responses-API stream (the
    # ``response.completed`` / ``response.incomplete`` / ``response.failed``
    # event carries the full response including usage).
    responses_final: Optional[Dict[str, Any]] = None
    _saw_responses_events: bool = False
    # Usage accumulated from an Anthropic Messages stream. Kept apart from
    # ``last_chunk`` because that stream ends on ``message_stop``, which carries
    # no usage and would otherwise erase the figures that arrived one event
    # earlier — see _consume_messages_event.
    messages_usage: Optional[Dict[str, Any]] = None
    _saw_messages_events: bool = False
    # True once message_delta's usage has arrived — the only event whose
    # output_tokens is settled. message_start's is a one-token placeholder
    # that must not stand in for the running count; see streamed_tokens.
    _messages_final_usage: bool = False
    # The client may close immediately after receiving the protocol's terminal
    # event. Treat that as a completed response, even if the worker transport's
    # following stream_end frame has not been consumed yet.
    terminal_event_received: bool = False
    # An upstream ``data: {"error": {...}}`` frame delivered mid-stream with an
    # HTTP 200 (a content filter, context-length, or rate limit that fired after
    # generation began). The bytes are forwarded to the client, but the request
    # is not a success.
    upstream_error: Optional[Dict[str, Any]] = None
    # Text deltas seen so far. The exact completion count only arrives with the
    # terminal usage event, which is no help to anyone watching the request run
    # — so the delta count stands in for it until then. See streamed_tokens.
    delta_count: int = 0
    # The response id announced up front (``response.created`` and every
    # event that carries the response object repeat it). Echoed into the
    # synthetic ``response.failed`` terminal of a mid-flight failure, so a
    # Responses client can correlate the failure with the stream it read.
    responses_id: Optional[str] = None
    # The Response object the stream announced in ``response.created`` — the
    # full envelope a synthetic ``response.failed`` terminal completes, so
    # the failure carries everything the client already saw, not a skeleton.
    responses_created: Optional[Dict[str, Any]] = None
    # The highest ``sequence_number`` seen on the stream. The synthetic
    # terminal takes the next one, as the spec numbers its events.
    responses_sequence: Optional[int] = None
    _decoder: Any = field(
        default_factory=lambda: codecs.getincrementaldecoder("utf-8")(errors="replace"),
        repr=False,
    )
    # Set when a chat-completion delta carried non-text structure (see
    # _STRUCTURED_DELTA_KEYS). A mid-flight resume is text-only and must not
    # kick in for such a stream.
    saw_structured_delta: bool = False

    def feed(self, chunk: bytes | str) -> None:
        if isinstance(chunk, bytes):
            text = self._decoder.decode(chunk, final=False)
        else:
            text = self._decoder.decode(b"", final=True) + str(chunk)
            self._decoder.reset()
        self.buffer += text
        self._consume_complete_lines()

    def finish(self) -> None:
        self.buffer += self._decoder.decode(b"", final=True)
        self._decoder.reset()
        if not self.buffer:
            return
        remainder = self.buffer
        self.buffer = ""
        for line in remainder.splitlines():
            self._consume_line(line.rstrip("\r"))

    def streamed_tokens(self) -> Dict[str, int]:
        """Best current view of this request's tokens, mid-stream.

        Prompt tokens are exact as soon as the stream opens — every surface
        states them up front. Completion tokens are not: the count settles only
        in the terminal usage event, which is precisely the moment a live view
        stops being interesting. Until it arrives the text deltas are counted
        instead, one apiece.

        That is an approximation, and it is the right one to make: vLLM emits a
        delta per token, so it tracks the real figure closely, and speculative
        decoding is the case where it can undercount. It is only ever shown
        while the request is running — the settled usage replaces it on
        completion, so nothing is stored or billed from this.
        """
        usage = self.usage()
        prompt = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        if not isinstance(prompt, int):
            prompt = 0
        # A Messages stream's message_start already carries an
        # ``output_tokens`` figure — but it is a one-token placeholder, not a
        # count, and trusting it pins the live figure at 1 for the whole
        # generation. Until message_delta settles it, the deltas are the count.
        if self._saw_messages_events and not self._messages_final_usage:
            return {"prompt_tokens": prompt, "completion_tokens": self.delta_count}
        completion = usage.get("completion_tokens") or usage.get("output_tokens") or 0
        if not isinstance(completion, int) or completion <= 0:
            completion = self.delta_count
        return {"prompt_tokens": prompt, "completion_tokens": completion}

    def usage(self) -> Dict[str, Any]:
        if isinstance(self.responses_final, dict):
            usage = self.responses_final.get("usage")
            if isinstance(usage, dict):
                return usage
        if isinstance(self.messages_usage, dict) and self.messages_usage:
            return self.messages_usage
        if isinstance(self.last_chunk, dict):
            usage = self.last_chunk.get("usage")
            if isinstance(usage, dict):
                return usage
        return {}

    def settled_completion_tokens(self) -> Optional[int]:
        """The engine's own completion count, or None until it has settled.

        This is the only figure that can hold an explicit completion limit
        exactly: it is what the serving model's tokenizer actually counted,
        delivered in the terminal usage event. That event never arrives on a
        failed stream — precisely the mid-flight resume case — so this is None
        exactly when a takeover would otherwise have to guess. ``streamed_tokens``
        and the live view keep their delta-count approximation, which is the
        right number for a running indicator and the wrong one for enforcing a
        limit a caller set.
        """
        usage = self.usage()
        completion = usage.get("completion_tokens") or usage.get("output_tokens") or 0
        if isinstance(completion, int) and completion > 0:
            return completion
        return None

    def response_payload(self) -> Dict[str, Any]:
        # Responses-API stream: the terminal event already carries the complete
        # response (output items + usage) — log it verbatim. If the stream was
        # cut off before the terminal event, fall back to the accumulated text.
        if isinstance(self.responses_final, dict):
            return self.responses_final
        if self._saw_responses_events:
            return {"content": self.full_text}
        if self._saw_messages_events:
            # No chunk to rebuild from: an Anthropic stream never sends the
            # response as one object, only the events that assemble it.
            payload: Dict[str, Any] = {"content": self.full_text}
            if self.messages_usage:
                payload["usage"] = self.messages_usage
            return payload

        usage = self.usage()
        response_payload: Dict[str, Any] = {"content": self.full_text}
        base_payload = None

        if self.first_chunk:
            base_payload = self.first_chunk.copy()
        if self.last_chunk:
            if base_payload is None:
                base_payload = self.last_chunk.copy()
            else:
                for key, value in self.last_chunk.items():
                    if key not in base_payload:
                        base_payload[key] = value

        if base_payload:
            response_payload = base_payload
            # The rebuild prefers the first chunk, so a malformed choices
            # element the feed guard skipped is still sitting in it. Validate
            # the complete shape before assigning, as _consume_line does:
            # a non-dict entry carries no delta.
            choices = response_payload.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                choices[0]["delta"] = {"content": self.full_text}
        if usage:
            response_payload["usage"] = usage
        return response_payload

    def failed_response_event(self, message: str) -> Optional[Dict[str, Any]]:
        """The synthetic ``response.failed`` terminal for a mid-flight failure.

        A /v1/responses client has been reading numbered ``response.*``
        events, and the terminal the protocol expects is the Response object
        it saw in ``response.created`` — the full envelope, not a skeleton —
        now failed, under the next sequence number. When the stream failed
        before a created envelope arrived there is nothing to complete and
        no sequence to continue, so the event degrades to the announced id
        (or None when that too is absent and the caller keeps its fallback).
        """
        if self.responses_created:
            response = copy.deepcopy(self.responses_created)
        elif self.responses_id:
            response = {"id": self.responses_id, "object": "response"}
        else:
            return None
        response["status"] = "failed"
        response["error"] = {"code": "server_error", "message": message}
        event: Dict[str, Any] = {"type": "response.failed", "response": response}
        if self.responses_sequence is not None:
            event["sequence_number"] = self.responses_sequence + 1
        return event

    def _consume_complete_lines(self) -> None:
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            self._consume_line(line.rstrip("\r"))

    def _consume_line(self, line: str) -> None:
        stripped = line.strip()
        if not stripped:
            return
        if stripped == "data: [DONE]":
            self.terminal_event_received = True
            return
        if not stripped.startswith("data: "):
            return
        try:
            blob = json.loads(stripped[6:])
        except json.JSONDecodeError:
            return
        if not isinstance(blob, dict):
            return

        blob_error = blob.get("error")
        if isinstance(blob_error, dict) and blob_error:
            self.upstream_error = blob_error
            return
        if isinstance(blob_error, str) and blob_error:
            self.upstream_error = {"message": blob_error}
            return

        event_type = blob.get("type")
        if isinstance(event_type, str) and event_type.startswith("response."):
            if event_type in {"response.completed", "response.incomplete", "response.failed"}:
                self.terminal_event_received = True
            self._consume_responses_event(event_type, blob)
            return
        if isinstance(event_type, str) and event_type in _MESSAGES_EVENT_TYPES:
            if event_type == "message_stop":
                self.terminal_event_received = True
            self._consume_messages_event(event_type, blob)
            return

        self.last_chunk = blob
        if self.first_chunk is None:
            self.first_chunk = blob

        choices = blob.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            # Every other blob field in this parser is type-checked before use;
            # the element was not. An upstream that sends {"choices": [null]} or
            # {"choices": ["text"]} would otherwise call .get on a non-dict and
            # raise AttributeError mid-stream, aborting the request being
            # streamed. A non-dict first element simply carries no delta.
            delta = first_choice.get("delta", {}) if isinstance(first_choice, dict) else None
            if isinstance(delta, dict):
                content = delta.get("content", "")
                # Structured output can ride in the same delta as a content
                # piece, so the flag is checked independently — an `elif`
                # would miss it whenever both are present, and a mid-flight
                # resume must not continue a stream that is emitting tool
                # calls.
                if any(key in delta for key in _STRUCTURED_DELTA_KEYS):
                    self.saw_structured_delta = True
                if content:
                    self.full_text += content
                    self.delta_count += 1

    def _consume_responses_event(self, event_type: str, blob: Dict[str, Any]) -> None:
        """Consume one Responses-API SSE event (``{"type": "response.*", ...}``)."""
        self._saw_responses_events = True
        if self.responses_id is None:
            response = blob.get("response")
            if isinstance(response, dict) and response.get("id"):
                self.responses_id = str(response["id"])
        # The spec numbers every event; the highest one seen is what a
        # synthetic terminal must continue from. A resumed stream opens a
        # new upstream response and can renumber from zero, so the numbers
        # only ever move forward.
        sequence = blob.get("sequence_number")
        if isinstance(sequence, int) and (self.responses_sequence is None or sequence > self.responses_sequence):
            self.responses_sequence = sequence
        if event_type == "response.created":
            response = blob.get("response")
            if isinstance(response, dict):
                self.responses_created = response
        if event_type == "response.output_text.delta":
            delta = blob.get("delta")
            if isinstance(delta, str):
                self.full_text += delta
                self.delta_count += 1
        elif event_type in {"response.completed", "response.incomplete", "response.failed"}:
            response = blob.get("response")
            if isinstance(response, dict):
                self.responses_final = response
            # A terminal ``response.failed`` is the Responses-API equivalent of a
            # mid-stream ``data: {"error": {...}}`` frame: generation began, the
            # bytes reached the client, but the request is not a success and must
            # not be billed. ``response.incomplete`` is deliberately excluded: it
            # means the generation stopped at max_output_tokens or a content
            # filter, and the partial output it carries is real, billed usage.
            if event_type == "response.failed":
                err = response.get("error") if isinstance(response, dict) else None
                if isinstance(err, dict) and err:
                    self.upstream_error = err
                elif isinstance(err, str) and err:
                    self.upstream_error = {"message": err}
                else:
                    self.upstream_error = {"message": "Responses API stream reported response.failed"}

    def _consume_messages_event(self, event_type: str, blob: Dict[str, Any]) -> None:
        """Consume one Anthropic Messages SSE event.

        This is what Claude Code speaks, so it covers every session set up
        through the AI-tools page — and none of it was being counted. The usage
        arrives in two places and neither is the last event:

            message_start   {"message": {"usage": {"input_tokens": 14, …}}}
            content_block_delta …
            message_delta   {"usage": {"input_tokens": 14, "output_tokens": 2}}
            message_stop    — nothing

        Reading the final chunk's ``usage`` therefore found ``message_stop`` and
        came away empty, so every such request was logged with no tokens at all.
        Both events are merged instead, later winning, since message_delta
        carries the settled figures.
        """
        self._saw_messages_events = True
        if event_type == "content_block_delta":
            delta = blob.get("delta")
            if isinstance(delta, dict):
                text = delta.get("text")
                if isinstance(text, str):
                    self.full_text += text
                    self.delta_count += 1
            return

        usage: Any = None
        if event_type == "message_start":
            message = blob.get("message")
            if isinstance(message, dict):
                usage = message.get("usage")
        elif event_type == "message_delta":
            usage = blob.get("usage")
        if not isinstance(usage, dict):
            return

        if event_type == "message_delta":
            self._messages_final_usage = True
        merged = dict(self.messages_usage or {})
        merged.update(usage)
        # Anthropic omits a total — it is the sum, so it says it once. Logos
        # stores one row per token type and the statistics page reads
        # total_tokens, so a stream without it lands as zero tokens used.
        prompt = merged.get("input_tokens")
        completion = merged.get("output_tokens")
        if isinstance(prompt, int) and isinstance(completion, int):
            merged["total_tokens"] = prompt + completion
        self.messages_usage = merged


def _usage_tokens_from_payload(
    response_payload: Any,
    request_payload: Any = None,
    path: str = "",
    billable_request: bool = True,
) -> Dict[str, int]:
    """Canonical token usage for a response, merged with the derived non-token
    billable quantities (``billed_requests``, characters, images, ...) so the
    stored ``usage_tokens`` rows carry everything ``logos_price_usage`` prices."""
    usage, _ = finalize_billing_inputs(request_payload, response_payload, path)
    if not billable_request:
        usage.pop("billed_requests", None)
    return usage

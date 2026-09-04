"""Billable quantities the provider's ``usage`` object does not report.

The litellm catalogue prices some models per character, per request, per image,
per pixel, per OCR page or per web-search query. Those counts are not in the
response ``usage`` block, so they are derived here from the request/response
payloads and merged into the usage dict alongside the token counts. Each is
priced only when the model actually carries a matching non-token catalogue price
(``logos_price_usage`` enforces token/character mutual exclusivity); otherwise it
is free, exactly as today.
"""

from __future__ import annotations

import base64
import math
import re
import struct
from typing import Any

_IMAGE_PART_TYPES = {"image_url", "image", "input_image"}
_VIDEO_PART_TYPES = {"video_url", "video", "input_video"}
_SIZE_RE = re.compile(r"(\d+)\s*[xX]\s*(\d+)")
_MAX_EMBEDDED_IMAGE_BYTES = 32 * 1024 * 1024


def _embedded_image_bytes(part: dict) -> bytes | None:
    """Return bounded inline image bytes; remote URLs are never fetched."""
    for candidate in (part.get("image_url"), part.get("image"), part.get("source")):
        if isinstance(candidate, dict):
            candidate = candidate.get("url") or candidate.get("data") or candidate.get("base64")
        if not isinstance(candidate, str):
            continue
        encoded = candidate.split(",", 1)[1] if candidate.startswith("data:") and "," in candidate else candidate
        if encoded.startswith(("http://", "https://")) or len(encoded) > _MAX_EMBEDDED_IMAGE_BYTES * 4 // 3 + 8:
            continue
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            continue
        if len(raw) <= _MAX_EMBEDDED_IMAGE_BYTES:
            return raw
    return None


def _image_dimensions(raw: bytes) -> tuple[int, int] | None:
    """Read PNG, GIF, or JPEG dimensions without decoding image pixels."""
    if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) >= 24:
        return struct.unpack(">II", raw[16:24])
    if raw[:6] in {b"GIF87a", b"GIF89a"} and len(raw) >= 10:
        return struct.unpack("<HH", raw[6:10])
    if raw.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 9 <= len(raw):
            if raw[offset] != 0xFF:
                offset += 1
                continue
            marker = raw[offset + 1]
            offset += 2
            if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
                continue
            length = int.from_bytes(raw[offset : offset + 2], "big")
            if length < 2 or offset + length > len(raw):
                break
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                return (
                    int.from_bytes(raw[offset + 5 : offset + 7], "big"),
                    int.from_bytes(raw[offset + 3 : offset + 5], "big"),
                )
            offset += length
    return None


def _text_len_of(content: Any) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                total += len(part["text"])
            elif isinstance(part, dict):
                # Responses API input/output items wrap their content parts in
                # a message object: {"role": ..., "content": [...]}. Recurse
                # so character-priced models see the actual text.
                total += _text_len_of(part.get("content"))
            elif isinstance(part, str):
                total += len(part)
        return total
    return 0


def _count_images(messages: Any) -> int:
    n = 0
    for msg in messages or []:
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, list):
            n += sum(1 for p in content if isinstance(p, dict) and p.get("type") in _IMAGE_PART_TYPES)
    return n


def _count_images_in_content(content: Any) -> int:
    """Count image parts in either Chat Completions or Responses nesting."""
    if not isinstance(content, list):
        return 0
    total = 0
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") in _IMAGE_PART_TYPES:
            total += 1
        total += _count_images_in_content(part.get("content"))
    return total


def _image_pixels_in_content(content: Any) -> int:
    """Sum pixels for images whose dimensions are knowable without guessing.

    A part is counted when it carries an explicit width/height or size string,
    or when it embeds bounded inline bytes whose header we can read (PNG, GIF,
    JPEG). Remote URLs are never fetched and undecodable blobs stay unbilled by
    pixel, so the count is always reproducible from the request alone.
    """
    if not isinstance(content, list):
        return 0
    total = 0
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") in _IMAGE_PART_TYPES:
            width = part.get("width")
            height = part.get("height")
            if (
                isinstance(width, int)
                and not isinstance(width, bool)
                and width > 0
                and isinstance(height, int)
                and not isinstance(height, bool)
                and height > 0
            ):
                total += width * height
            else:
                match = _SIZE_RE.fullmatch(str(part.get("size", "")).strip())
                if match:
                    total += int(match.group(1)) * int(match.group(2))
                else:
                    raw = _embedded_image_bytes(part)
                    dimensions = _image_dimensions(raw) if raw is not None else None
                    if dimensions and dimensions[0] > 0 and dimensions[1] > 0:
                        total += dimensions[0] * dimensions[1]
        total += _image_pixels_in_content(part.get("content"))
    return total


def _media_duration_ms(content: Any, media_types: set[str]) -> int:
    """Sum explicit media durations recursively; opaque media is not guessed."""
    if not isinstance(content, list):
        return 0
    total = 0
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") in media_types:
            raw = part.get("duration", part.get("duration_seconds", part.get("durationSeconds")))
            try:
                seconds = float(raw)
            except (TypeError, ValueError):
                seconds = -1
            if math.isfinite(seconds) and seconds >= 0:
                total += math.ceil(seconds * 1000)
        total += _media_duration_ms(part.get("content"), media_types)
    return total


def derive_billable_quantities(
    request_payload: Any,
    response_payload: Any,
    path: str,
) -> dict[str, int]:
    """Return the non-token billable quantities for one response.

    Always includes ``billed_requests`` (1). Other keys appear only when the
    payload actually contains the thing they count, so a plain chat call yields
    just ``billed_requests`` plus the character totals.
    """
    req = request_payload if isinstance(request_payload, dict) else {}
    resp = response_payload if isinstance(response_payload, dict) else {}
    path = path or ""
    out: dict[str, int] = {"billed_requests": 1}

    # --- characters: request side
    in_chars = 0
    for msg in req.get("messages", []) or []:
        if isinstance(msg, dict):
            in_chars += _text_len_of(msg.get("content"))
    if isinstance(req.get("input"), (str, list)):
        in_chars += _text_len_of(req["input"])
    if isinstance(req.get("prompt"), str):
        in_chars += len(req["prompt"])
    if isinstance(req.get("prompt"), list):
        in_chars += _text_len_of(req["prompt"])
    if in_chars:
        out["billed_input_characters"] = in_chars

    # --- characters: response side
    out_chars = 0
    for choice in resp.get("choices", []) or []:
        if not isinstance(choice, dict):
            continue
        # A sync choice carries ``message``; a streamed chunk carries ``delta``.
        # They are disjoint, but count one or the other, never both, so a
        # reconstructed streaming payload is charged exactly once.
        msg = choice.get("message")
        if isinstance(msg, dict):
            out_chars += _text_len_of(msg.get("content"))
        elif isinstance(choice.get("delta"), dict):
            out_chars += _text_len_of(choice["delta"].get("content"))
        if isinstance(choice.get("text"), str):
            out_chars += len(choice["text"])
    for item in resp.get("output", []) or []:
        if isinstance(item, dict):
            out_chars += _text_len_of(item.get("content"))
    # Anthropic Messages responses (and the streaming accumulator's fallback for
    # a cut-off Responses stream) put the text at the payload root as ``content``
    # — a string when reconstructed from a stream, a list of parts when sync.
    if "choices" not in resp and "output" not in resp:
        out_chars += _text_len_of(resp.get("content"))
    if out_chars:
        out["billed_output_characters"] = out_chars

    # --- images in the request
    images = _count_images(req.get("messages")) + _count_images_in_content(req.get("input"))
    if images:
        out["billed_input_images"] = images
    input_pixels = _image_pixels_in_content(req.get("input"))
    for message in req.get("messages", []) or []:
        if isinstance(message, dict):
            input_pixels += _image_pixels_in_content(message.get("content"))
    if input_pixels:
        out["billed_input_pixels"] = input_pixels
    input_video_ms = _media_duration_ms(req.get("input"), _VIDEO_PART_TYPES)
    for message in req.get("messages", []) or []:
        if isinstance(message, dict):
            input_video_ms += _media_duration_ms(message.get("content"), _VIDEO_PART_TYPES)
    if input_video_ms:
        out["billed_input_video_milliseconds"] = input_video_ms
        if input_video_ms > 8_000:
            out["billed_input_video_milliseconds_above_8s"] = input_video_ms
        if input_video_ms > 15_000:
            out["billed_input_video_milliseconds_above_15s"] = input_video_ms

    # --- output images and pixels for image generation / edits
    #
    # Both the flat per-image price and the per-pixel price count the images the
    # provider actually returned. Prefer the response ``data`` length because
    # providers may return fewer images than requested; fall back to a valid
    # request ``n`` before a response exists. An empty ``data`` list yields
    # neither key.
    if "images/generations" in path or "images/edits" in path:
        response_images = resp.get("data")
        if isinstance(response_images, list):
            output_images = len(response_images)
        else:
            requested_images = req.get("n", 1)
            output_images = (
                requested_images
                if isinstance(requested_images, int) and not isinstance(requested_images, bool) and requested_images > 0
                else 1
            )
        if output_images:
            out["billed_output_images"] = output_images
            match = _SIZE_RE.search(str(req.get("size", "")))
            if match:
                # `size` describes generated/edited output, not source-image input.
                out["billed_output_pixels"] = int(match.group(1)) * int(match.group(2)) * output_images

    # --- OCR pages
    pages = resp.get("pages")
    if isinstance(pages, list) and pages:
        out["billed_ocr_pages"] = len(pages)
        # Mistral OCR charges annotation per processed page when the optional
        # document annotation format is requested; response citation counts are
        # not page counts and must not be used here.
        if req.get("document_annotation_format") is not None:
            out["billed_annotation_pages"] = len(pages)

    # --- web-search tool calls in the response
    queries = 0
    for item in resp.get("output", []) or []:
        if isinstance(item, dict) and item.get("type") in {"web_search_call", "web_search"}:
            # Some providers expose multiple actual queries within one tool
            # invocation. Prefer that authoritative count; otherwise one call
            # is one billable query.
            action = item.get("action")
            query_list = action.get("queries") if isinstance(action, dict) else None
            queries += len(query_list) if isinstance(query_list, list) and query_list else 1
    if queries:
        search_context = req.get("search_context_size")
        if search_context not in {"low", "medium", "high"}:
            search_context = None
        for tool in req.get("tools", []) or []:
            if not isinstance(tool, dict) or tool.get("type") not in {"web_search", "web_search_preview"}:
                continue
            candidate = tool.get("search_context_size")
            if candidate in {"low", "medium", "high"}:
                search_context = candidate
                break
        out[
            f"billed_search_queries_{search_context}" if search_context in {"low", "high"} else "billed_search_queries"
        ] = queries
        out[
            f"billed_search_prompts_{search_context}" if search_context in {"low", "high"} else "billed_search_prompts"
        ] = 1

    # Native Gemini grounding exposes the individual executed searches in
    # groundingMetadata. Keep Maps separate because its catalogue price differs
    # from ordinary Google Search grounding.
    maps_requested = any(
        isinstance(tool, dict) and tool.get("type") in {"google_maps", "maps", "googleMaps"}
        for tool in (req.get("tools", []) or [])
    )
    if maps_requested:
        maps_queries = 0
        for candidate in resp.get("candidates", []) or []:
            metadata = candidate.get("groundingMetadata") if isinstance(candidate, dict) else None
            reported = metadata.get("webSearchQueries") if isinstance(metadata, dict) else None
            if isinstance(reported, list):
                maps_queries += len(reported)
        if maps_queries:
            out["billed_google_maps_queries"] = maps_queries

    # Bedrock ApplyGuardrail returns the exact policy-unit counters that its
    # structured catalogue price object names. Copy only the documented unit
    # counters; arbitrary provider fields never become billable quantities.
    guardrail_usage = resp.get("usage")
    for name in (
        "automatedReasoningPolicyUnits",
        "contentPolicyImageUnits",
        "contentPolicyUnits",
        "contextualGroundingPolicyUnits",
        "sensitiveInformationPolicyFreeUnits",
        "sensitiveInformationPolicyUnits",
        "topicPolicyUnits",
        "wordPolicyUnits",
    ):
        count = guardrail_usage.get(name) if isinstance(guardrail_usage, dict) else None
        if isinstance(count, int) and not isinstance(count, bool) and count > 0:
            out[f"billed_guardrail_{name}"] = count

    # A container creation is one new code-interpreter session. Responses that
    # merely use or list existing containers must not create another session
    # charge, so require the single-object create shape (a top-level ``id`` and
    # no ``data`` list envelope) rather than keying off the path alone.
    normalized_path = path.strip("/")
    if (
        normalized_path.endswith("containers")
        and not resp.get("error")
        and isinstance(resp.get("id"), str)
        and not isinstance(resp.get("data"), list)
    ):
        out["billed_code_interpreter_sessions"] = 1

    # Duration-priced generated media. Providers may return the realized
    # duration; video APIs commonly only expose the accepted duration in the
    # request. Record milliseconds so fractional seconds remain reproducible.
    is_output_media = "audio/speech" in path or "/videos" in path or path.startswith("videos")
    if is_output_media:
        duration = resp.get("duration", req.get("duration", req.get("seconds")))
        try:
            seconds = float(duration)
        except (TypeError, ValueError):
            seconds = -1
        if math.isfinite(seconds) and seconds >= 0:
            resolution = str(req.get("resolution", req.get("size", ""))).lower()
            quantity = (
                "billed_output_milliseconds_4k"
                if "4k" in resolution
                else "billed_output_milliseconds_1080p" if "1080" in resolution else "billed_output_milliseconds"
            )
            out[quantity] = math.ceil(seconds * 1000)

    return out

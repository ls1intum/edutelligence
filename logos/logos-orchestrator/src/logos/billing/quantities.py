"""Derive billable counts that providers do not include in token usage."""

import base64
import math
import re
import struct
from typing import Any

IMAGE_TYPES = {"image_url", "image", "input_image"}
VIDEO_TYPES = {"video_url", "video", "input_video"}
IMAGE_SIZE = re.compile(r"(\d+)\s*[xX]\s*(\d+)")
MAX_IMAGE_BYTES = 32 * 1024 * 1024
GUARDRAIL_COUNTERS = (
    "automatedReasoningPolicyUnits",
    "contentPolicyImageUnits",
    "contentPolicyUnits",
    "contextualGroundingPolicyUnits",
    "sensitiveInformationPolicyFreeUnits",
    "sensitiveInformationPolicyUnits",
    "topicPolicyUnits",
    "wordPolicyUnits",
)


def _text_characters(content: Any) -> int:
    """Count text characters in nested content."""
    if isinstance(content, str):
        return len(content)
    if not isinstance(content, list):
        return 0
    return sum(
        (
            len(part["text"])
            if isinstance(part, dict) and isinstance(part.get("text"), str)
            else (
                _text_characters(part.get("content"))
                if isinstance(part, dict)
                else len(part) if isinstance(part, str) else 0
            )
        )
        for part in content
    )


def _count_parts(content: Any, accepted_types: set[str]) -> int:
    """Count matching parts in nested content."""
    if not isinstance(content, list):
        return 0
    count = 0
    for part in content:
        if isinstance(part, dict):
            count += part.get("type") in accepted_types
            count += _count_parts(part.get("content"), accepted_types)
    return count


def _embedded_image(part: dict[str, Any]) -> bytes | None:
    """Decode a bounded inline image without fetching URLs."""
    for value in (part.get("image_url"), part.get("image"), part.get("source")):
        if isinstance(value, dict):
            value = value.get("url") or value.get("data") or value.get("base64")
        if not isinstance(value, str):
            continue
        encoded = value.split(",", 1)[1] if value.startswith("data:") and "," in value else value
        if encoded.startswith(("http://", "https://")) or len(encoded) > MAX_IMAGE_BYTES * 4 // 3 + 8:
            continue
        try:
            image = base64.b64decode(encoded, validate=True)
        except (TypeError, ValueError):
            continue
        if len(image) <= MAX_IMAGE_BYTES:
            return image
    return None


def _image_dimensions(image: bytes) -> tuple[int, int] | None:
    """Read PNG, GIF, or JPEG dimensions from its header."""
    if image.startswith(b"\x89PNG\r\n\x1a\n") and len(image) >= 24:
        return struct.unpack(">II", image[16:24])
    if image[:6] in {b"GIF87a", b"GIF89a"} and len(image) >= 10:
        return struct.unpack("<HH", image[6:10])
    if not image.startswith(b"\xff\xd8"):
        return None
    offset = 2
    frame_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while offset + 9 <= len(image):
        if image[offset] != 0xFF:
            offset += 1
            continue
        marker = image[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        segment_length = int.from_bytes(image[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(image):
            break
        if marker in frame_markers:
            width = int.from_bytes(image[offset + 5 : offset + 7], "big")
            height = int.from_bytes(image[offset + 3 : offset + 5], "big")
            return width, height
        offset += segment_length
    return None


def _image_pixels(content: Any) -> int:
    """Count pixels when dimensions are known."""
    if not isinstance(content, list):
        return 0
    pixels = 0
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") in IMAGE_TYPES:
            width, height = part.get("width"), part.get("height")
            if all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in (width, height)):
                pixels += width * height
            elif match := IMAGE_SIZE.fullmatch(str(part.get("size", "")).strip()):
                pixels += int(match.group(1)) * int(match.group(2))
            elif (image := _embedded_image(part)) and (dimensions := _image_dimensions(image)):
                pixels += dimensions[0] * dimensions[1]
        pixels += _image_pixels(part.get("content"))
    return pixels


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _media_milliseconds(content: Any) -> int:
    if not isinstance(content, list):
        return 0
    milliseconds = 0
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") in VIDEO_TYPES:
            duration = _number(part.get("duration", part.get("duration_seconds", part.get("durationSeconds"))))
            milliseconds += math.ceil(duration * 1000) if duration is not None else 0
        milliseconds += _media_milliseconds(part.get("content"))
    return milliseconds


def _message_content(messages: Any) -> list[Any]:
    return [message.get("content") for message in messages or [] if isinstance(message, dict)]


def _add_search_quantities(result: dict[str, int], request: dict, response: dict) -> None:
    query_count = 0
    for item in response.get("output", []) or []:
        if not isinstance(item, dict) or item.get("type") not in {"web_search_call", "web_search"}:
            continue
        action = item.get("action")
        queries = action.get("queries") if isinstance(action, dict) else None
        query_count += len(queries) if isinstance(queries, list) and queries else 1
    if not query_count:
        return
    context = request.get("search_context_size")
    for tool in request.get("tools", []) or []:
        if (
            isinstance(tool, dict)
            and tool.get("type") in {"web_search", "web_search_preview"}
            and tool.get("search_context_size") in {"low", "medium", "high"}
        ):
            context = tool["search_context_size"]
            break
    suffix = f"_{context}" if context in {"low", "high"} else ""
    result[f"billed_search_queries{suffix}"] = query_count
    result[f"billed_search_prompts{suffix}"] = 1


def derive_billable_quantities(request_payload: Any, response_payload: Any, path: str) -> dict[str, int]:
    """Return non-token quantities used to price one response."""
    request = request_payload if isinstance(request_payload, dict) else {}
    response = response_payload if isinstance(response_payload, dict) else {}
    request_path = path or ""
    result = {"billed_requests": 1}
    message_content = _message_content(request.get("messages"))

    input_characters = sum(_text_characters(content) for content in message_content)
    input_characters += _text_characters(request.get("input"))
    input_characters += _text_characters(request.get("prompt"))
    if input_characters:
        result["billed_input_characters"] = input_characters

    output_characters = 0
    for choice in response.get("choices", []) or []:
        if isinstance(choice, dict):
            message, delta = choice.get("message"), choice.get("delta")
            if isinstance(message, dict):
                output_characters += _text_characters(message.get("content"))
            elif isinstance(delta, dict):
                output_characters += _text_characters(delta.get("content"))
            if isinstance(choice.get("text"), str):
                output_characters += len(choice["text"])
    output_characters += sum(
        _text_characters(item.get("content")) for item in response.get("output", []) or [] if isinstance(item, dict)
    )
    if "choices" not in response and "output" not in response:
        output_characters += _text_characters(response.get("content"))
    if output_characters:
        result["billed_output_characters"] = output_characters

    input_content = [request.get("input"), *message_content]
    image_count = sum(_count_parts(content, IMAGE_TYPES) for content in input_content)
    pixel_count = sum(_image_pixels(content) for content in input_content)
    video_milliseconds = sum(_media_milliseconds(content) for content in input_content)
    if image_count:
        result["billed_input_images"] = image_count
    if pixel_count:
        result["billed_input_pixels"] = pixel_count
    if video_milliseconds:
        result["billed_input_video_milliseconds"] = video_milliseconds
        if video_milliseconds > 8_000:
            result["billed_input_video_milliseconds_above_8s"] = video_milliseconds
        if video_milliseconds > 15_000:
            result["billed_input_video_milliseconds_above_15s"] = video_milliseconds

    image_output_paths = ("images/generations", "images/edits", "images/variations")
    if any(image_path in request_path for image_path in image_output_paths):
        returned = response.get("data")
        requested = request.get("n", 1)
        valid_requested_count = isinstance(requested, int) and not isinstance(requested, bool) and requested > 0
        image_count = len(returned) if isinstance(returned, list) else requested if valid_requested_count else 1
        if image_count:
            result["billed_output_images"] = image_count
            if match := IMAGE_SIZE.search(str(request.get("size", ""))):
                result["billed_output_pixels"] = int(match.group(1)) * int(match.group(2)) * image_count

    pages = response.get("pages")
    if isinstance(pages, list) and pages:
        result["billed_ocr_pages"] = len(pages)
        if request.get("document_annotation_format") is not None:
            result["billed_annotation_pages"] = len(pages)
    _add_search_quantities(result, request, response)

    maps_requested = any(
        isinstance(tool, dict) and tool.get("type") in {"google_maps", "maps", "googleMaps"}
        for tool in request.get("tools", []) or []
    )
    if maps_requested:
        maps_queries = 0
        for candidate in response.get("candidates", []) or []:
            metadata = candidate.get("groundingMetadata") if isinstance(candidate, dict) else None
            reported_queries = metadata.get("webSearchQueries") if isinstance(metadata, dict) else None
            if isinstance(reported_queries, list):
                maps_queries += len(reported_queries)
        if maps_queries:
            result["billed_google_maps_queries"] = maps_queries

    usage = response.get("usage")
    if isinstance(usage, dict):
        for name in GUARDRAIL_COUNTERS:
            count = usage.get(name)
            if isinstance(count, int) and not isinstance(count, bool) and count > 0:
                result[f"billed_guardrail_{name}"] = count

    creates_container = (
        request_path.strip("/").endswith("containers")
        and not response.get("error")
        and isinstance(response.get("id"), str)
        and not isinstance(response.get("data"), list)
    )
    if creates_container:
        result["billed_code_interpreter_sessions"] = 1

    if "audio/speech" in request_path or "/videos" in request_path or request_path.startswith("videos"):
        duration = _number(response.get("duration", request.get("duration", request.get("seconds"))))
        if duration is not None:
            resolution = str(request.get("resolution", request.get("size", ""))).lower()
            if "4k" in resolution:
                name = "billed_output_milliseconds_4k"
            elif "1080" in resolution:
                name = "billed_output_milliseconds_1080p"
            else:
                name = "billed_output_milliseconds"
            result[name] = math.ceil(duration * 1000)
    return result

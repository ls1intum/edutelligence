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

import re
from typing import Any

_IMAGE_PART_TYPES = {"image_url", "image", "input_image"}
_SIZE_RE = re.compile(r"(\d+)\s*[xX]\s*(\d+)")


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
        msg = choice.get("message")
        if isinstance(msg, dict):
            out_chars += _text_len_of(msg.get("content"))
        if isinstance(choice.get("text"), str):
            out_chars += len(choice["text"])
    for item in resp.get("output", []) or []:
        if isinstance(item, dict):
            out_chars += _text_len_of(item.get("content"))
    if out_chars:
        out["billed_output_characters"] = out_chars

    # --- images in the request
    images = _count_images(req.get("messages")) + _count_images_in_content(req.get("input"))
    if images:
        out["billed_input_images"] = images

    # Flat per-output-image catalogue prices are distinct from pixel prices.
    # Prefer the response count because providers may return fewer images than
    # requested; fall back to a valid request ``n`` before a response exists.
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

    # --- pixels for image generation / edits
    if "images/generations" in path or "images/edits" in path:
        match = _SIZE_RE.search(str(req.get("size", "")))
        if match:
            n = req.get("n", 1)
            n = n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else 1
            # `size` describes generated/edited output, not source-image input.
            out["billed_output_pixels"] = int(match.group(1)) * int(match.group(2)) * n

    # --- OCR pages
    pages = resp.get("pages")
    if isinstance(pages, list) and pages:
        out["billed_ocr_pages"] = len(pages)
        # Catalogues that express OCR in credits currently expose one result
        # page per consumed credit. Keeping a separate quantity lets either
        # price vocabulary be selected without charging both unless both are
        # explicitly configured.
        out["billed_ocr_credits"] = len(pages)
        # Mistral OCR charges annotation per processed page when the optional
        # document annotation format is requested; response citation counts are
        # not page counts and must not be used here.
        if req.get("document_annotation_format") is not None:
            out["billed_annotation_pages"] = len(pages)

    # --- web-search tool calls in the response
    queries = 0
    for item in resp.get("output", []) or []:
        if isinstance(item, dict) and item.get("type") in {"web_search_call", "web_search"}:
            queries += 1
    if queries:
        out["billed_search_queries"] = queries

    return out

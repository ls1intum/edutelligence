"""Request-body helpers for OpenAI-compatible multipart uploads.

The normal Logos inference pipeline passes JSON-compatible dictionaries between
the orchestrator, scheduler, and worker nodes. Audio transcription requests are
different: OpenAI and Azure both require ``multipart/form-data`` with binary
file parts. This module keeps a JSON-serializable representation of those parts
inside the existing payload dictionary so the request can traverse every Logos
execution path without leaking audio bytes into usage logs.
"""

import base64
import binascii
import os
from typing import Any, Dict, Iterable, Tuple

from fastapi import HTTPException, Request
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException

MULTIPART_PAYLOAD_KEY = "_logos_multipart"
MAX_AUDIO_UPLOAD_BYTES = int(os.getenv("LOGOS_MAX_AUDIO_UPLOAD_BYTES", str(25 * 1024 * 1024)))
MAX_AUDIO_FORM_FIELD_BYTES = int(os.getenv("LOGOS_MAX_AUDIO_FORM_FIELD_BYTES", str(64 * 1024)))
MAX_AUDIO_REQUEST_BYTES = int(os.getenv("LOGOS_MAX_AUDIO_REQUEST_BYTES", str(MAX_AUDIO_UPLOAD_BYTES + 5 * 1024 * 1024)))
_AUDIO_UPLOAD_OPERATIONS = frozenset({"audio/transcriptions", "audio/translations"})
_METERED_WHISPER_RAW_FORMATS = frozenset({"text", "srt", "vtt"})


def is_audio_upload_path(path: str) -> bool:
    """Return whether an inbound path addresses an audio file-upload API."""
    normalized = (path or "").strip("/")
    for prefix in ("jobs/", "openai/", "v1/", "v2/"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    return normalized in _AUDIO_UPLOAD_OPERATIONS


def is_multipart_payload(payload: object) -> bool:
    """Return whether ``payload`` contains Logos' multipart representation."""
    return isinstance(payload, dict) and isinstance(payload.get(MULTIPART_PAYLOAD_KEY), dict)


async def parse_audio_upload(request: Request) -> Dict[str, Any]:
    """Parse and validate an OpenAI-compatible transcription/translation upload.

    Binary file contents are base64 encoded so the payload remains safe to send
    through the worker-node JSON command channel. The 25 MiB default mirrors the
    documented OpenAI and Azure Whisper limit and is configurable for compatible
    backends through ``LOGOS_MAX_AUDIO_UPLOAD_BYTES``.
    """
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise HTTPException(
            status_code=415,
            detail="Audio transcription requests require multipart/form-data",
        )

    _install_request_size_limit(request)
    try:
        form = await request.form(
            max_files=1,
            max_fields=64,
            max_part_size=MAX_AUDIO_FORM_FIELD_BYTES,
        )
    except (MultiPartException, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid multipart form data: {exc}") from exc

    return await _encode_form_data(form)


def _install_request_size_limit(request: Request) -> None:
    """Reject declared and chunked multipart bodies before unbounded spooling."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_AUDIO_REQUEST_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Audio request exceeds the {MAX_AUDIO_REQUEST_BYTES}-byte request limit",
                )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header")

    original_receive = request._receive
    received = 0

    async def limited_receive() -> dict[str, Any]:
        nonlocal received
        message = await original_receive()
        if message.get("type") == "http.request":
            received += len(message.get("body", b""))
            if received > MAX_AUDIO_REQUEST_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Audio request exceeds the {MAX_AUDIO_REQUEST_BYTES}-byte request limit",
                )
        return message

    request._receive = limited_receive


async def _encode_form_data(form: FormData) -> Dict[str, Any]:
    fields: list[list[str]] = []
    files: list[dict[str, Any]] = []
    body: Dict[str, Any] = {}

    for name, value in form.multi_items():
        if isinstance(value, UploadFile):
            content = bytearray()
            while chunk := await value.read(1024 * 1024):
                content.extend(chunk)
                if len(content) > MAX_AUDIO_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Audio file exceeds the {MAX_AUDIO_UPLOAD_BYTES}-byte upload limit",
                    )
            files.append(
                {
                    "field_name": name,
                    "filename": value.filename or "audio",
                    "content_type": value.content_type or "application/octet-stream",
                    "content_base64": base64.b64encode(bytes(content)).decode("ascii"),
                    "size": len(content),
                }
            )
            continue

        text = str(value)
        fields.append([name, text])
        body[name] = text

    body[MULTIPART_PAYLOAD_KEY] = {"fields": fields, "files": files}
    _validate_audio_upload(body)
    return body


def _validate_audio_upload(payload: Dict[str, Any]) -> None:
    model = str(payload.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="Audio transcription requests require a 'model' form field")

    multipart = payload[MULTIPART_PAYLOAD_KEY]
    files = multipart["files"]
    if len(files) != 1 or files[0].get("field_name") != "file":
        raise HTTPException(status_code=400, detail="Audio transcription requests require a 'file' upload")


def set_payload_field(payload: Dict[str, Any], name: str, value: Any) -> Dict[str, Any]:
    """Return a copy with a scalar field updated in JSON and multipart forms."""
    updated = {**payload, name: value}
    if not is_multipart_payload(payload):
        return updated

    multipart = payload[MULTIPART_PAYLOAD_KEY]
    fields = [list(item) for item in multipart.get("fields", []) if item[0] != name]
    fields.append([name, str(value).lower() if isinstance(value, bool) else str(value)])
    updated[MULTIPART_PAYLOAD_KEY] = {
        "fields": fields,
        "files": [dict(item) for item in multipart.get("files", [])],
    }
    return updated


def payload_requests_streaming(payload: Dict[str, Any]) -> bool:
    """Interpret the OpenAI ``stream`` field consistently for JSON and forms."""
    value = payload.get("stream", False)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def is_whisper_payload(payload: Dict[str, Any]) -> bool:
    """Return whether the selected model is a Whisper model."""
    return "whisper" in str(payload.get("model") or "").lower()


def metered_whisper_response_format(payload: Dict[str, Any], request_path: str) -> str | None:
    """Return a raw Whisper format that must be rendered from verbose JSON.

    Raw text/subtitle responses contain no usage object. Logos requests
    ``verbose_json`` upstream and renders the requested representation locally,
    retaining duration usage for billing without making a second provider call.
    """
    response_format = str(payload.get("response_format") or "json").lower()
    normalized_path = (request_path or "").strip("/")
    is_translation = normalized_path.endswith("audio/translations")
    if response_format in _METERED_WHISPER_RAW_FORMATS and (is_whisper_payload(payload) or is_translation):
        return response_format
    return None


def render_metered_whisper_response(payload: Dict[str, Any], response_format: str) -> tuple[bytes, str]:
    """Render a verbose Whisper JSON response as text, SRT, or WebVTT."""
    text = payload.get("text")
    if not isinstance(text, str):
        raise ValueError("Verbose transcription response is missing text")
    if response_format == "text":
        return text.encode("utf-8"), "text/plain; charset=utf-8"

    segments = payload.get("segments")
    if not isinstance(segments, list):
        raise ValueError("Verbose transcription response is missing segments")

    cues: list[str] = []
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            raise ValueError("Verbose transcription response contains an invalid segment")
        try:
            start = float(segment["start"])
            end = float(segment["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Verbose transcription segment is missing timestamps") from exc
        segment_text = str(segment.get("text") or "").strip()
        if response_format == "srt":
            cues.append(
                f"{index}\n"
                f"{_format_audio_timestamp(start, ',')} --> {_format_audio_timestamp(end, ',')}\n"
                f"{segment_text}"
            )
        elif response_format == "vtt":
            cues.append(
                f"{_format_audio_timestamp(start, '.')} --> {_format_audio_timestamp(end, '.')}\n" f"{segment_text}"
            )
        else:
            raise ValueError(f"Unsupported metered audio response format: {response_format}")

    prefix = "WEBVTT\n\n" if response_format == "vtt" else ""
    content_type = "text/vtt; charset=utf-8" if response_format == "vtt" else "application/x-subrip"
    return (prefix + "\n\n".join(cues) + "\n").encode("utf-8"), content_type


def _format_audio_timestamp(seconds: float, separator: str) -> str:
    total_milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{milliseconds:03d}"


def httpx_multipart_parts(payload: Dict[str, Any]) -> Tuple[list[tuple[str, str]], list[tuple[str, tuple]]]:
    """Decode a multipart payload into ``httpx`` data and files arguments."""
    if not is_multipart_payload(payload):
        raise ValueError("Payload is not multipart")

    multipart = payload[MULTIPART_PAYLOAD_KEY]
    fields = [(str(name), str(value)) for name, value in multipart.get("fields", [])]
    files: list[tuple[str, tuple]] = []
    for item in multipart.get("files", []):
        try:
            content = base64.b64decode(item["content_base64"], validate=True)
        except (KeyError, ValueError, binascii.Error) as exc:
            raise ValueError("Invalid encoded multipart file") from exc
        files.append(
            (
                str(item.get("field_name") or "file"),
                (
                    str(item.get("filename") or "audio"),
                    content,
                    str(item.get("content_type") or "application/octet-stream"),
                ),
            )
        )
    return fields, files


def sanitized_payload_for_logging(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Remove encoded file contents while retaining useful request metadata."""
    if not is_multipart_payload(payload):
        return payload

    sanitized = {key: value for key, value in payload.items() if key != MULTIPART_PAYLOAD_KEY}
    multipart = payload[MULTIPART_PAYLOAD_KEY]
    sanitized["files"] = [
        {
            "field_name": item.get("field_name"),
            "filename": item.get("filename"),
            "content_type": item.get("content_type"),
            "size": item.get("size"),
        }
        for item in multipart.get("files", [])
    ]
    return sanitized


def sanitized_headers_for_persistence(headers: Dict[str, str]) -> Dict[str, str]:
    """Redact credentials before request headers are written to durable storage."""
    sensitive_markers = ("authorization", "cookie", "key", "secret", "token")
    return {
        name: ("[REDACTED]" if any(marker in name.lower() for marker in sensitive_markers) else value)
        for name, value in headers.items()
    }


def multipart_field_names(payload: Dict[str, Any]) -> Iterable[str]:
    """Expose field names for focused validation and tests."""
    if not is_multipart_payload(payload):
        return ()
    return tuple(str(item[0]) for item in payload[MULTIPART_PAYLOAD_KEY].get("fields", []))

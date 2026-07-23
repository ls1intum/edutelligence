"""OpenAI-compatible multipart audio request handling."""

import base64
import importlib
import tempfile

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI
from starlette.datastructures import UploadFile

from logos.request_content import (
    MULTIPART_PAYLOAD_KEY,
    httpx_multipart_parts,
    is_audio_upload_path,
    metered_whisper_response_format,
    parse_audio_upload,
    payload_requests_streaming,
    render_metered_whisper_response,
    sanitized_headers_for_persistence,
    sanitized_payload_for_logging,
    set_payload_field,
)

request_content = importlib.import_module("logos.request_content")


def _multipart_payload() -> dict:
    return {
        "model": "whisper-1",
        "response_format": "verbose_json",
        "timestamp_granularities[]": "word",
        MULTIPART_PAYLOAD_KEY: {
            "fields": [
                ["model", "whisper-1"],
                ["response_format", "verbose_json"],
                ["timestamp_granularities[]", "segment"],
                ["timestamp_granularities[]", "word"],
            ],
            "files": [
                {
                    "field_name": "file",
                    "filename": "sample.wav",
                    "content_type": "audio/wav",
                    "content_base64": base64.b64encode(b"RIFFaudio").decode(),
                    "size": 9,
                }
            ],
        },
    }


def test_audio_upload_path_recognizes_all_public_routes():
    assert is_audio_upload_path("/v1/audio/transcriptions")
    assert is_audio_upload_path("/openai/audio/translations")
    assert is_audio_upload_path("/jobs/v1/audio/transcriptions")
    assert not is_audio_upload_path("/v1/chat/completions")


def test_multipart_parts_preserve_duplicate_fields_and_file_metadata():
    data, files = httpx_multipart_parts(_multipart_payload())

    assert data[-2:] == [
        ("timestamp_granularities[]", "segment"),
        ("timestamp_granularities[]", "word"),
    ]
    assert files == [("file", ("sample.wav", b"RIFFaudio", "audio/wav"))]


def test_set_payload_field_updates_the_forwarded_form():
    updated = set_payload_field(_multipart_payload(), "model", "canonical-whisper")
    data, _ = httpx_multipart_parts(updated)

    assert updated["model"] == "canonical-whisper"
    assert [item for item in data if item[0] == "model"] == [("model", "canonical-whisper")]


def test_logging_payload_excludes_audio_contents():
    sanitized = sanitized_payload_for_logging(_multipart_payload())

    assert MULTIPART_PAYLOAD_KEY not in sanitized
    assert sanitized["files"] == [
        {
            "field_name": "file",
            "filename": "sample.wav",
            "content_type": "audio/wav",
            "size": 9,
        }
    ]
    assert "content_base64" not in str(sanitized)


def test_persisted_headers_redact_credentials():
    sanitized = sanitized_headers_for_persistence(
        {
            "authorization": "Bearer lg-secret",
            "logos-key": "lg-secret",
            "x-custom-token": "secret",
            "content-type": "multipart/form-data; boundary=safe",
        }
    )

    assert sanitized == {
        "authorization": "[REDACTED]",
        "logos-key": "[REDACTED]",
        "x-custom-token": "[REDACTED]",
        "content-type": "multipart/form-data; boundary=safe",
    }


def test_stream_form_values_are_parsed_as_booleans():
    assert payload_requests_streaming({"stream": "true"})
    assert payload_requests_streaming({"stream": True})
    assert not payload_requests_streaming({"stream": "false"})
    assert not payload_requests_streaming({})


def test_raw_whisper_formats_are_rendered_from_metered_verbose_json():
    payload = _multipart_payload()
    payload["response_format"] = "srt"

    assert metered_whisper_response_format(payload, "v1/audio/transcriptions") == "srt"
    body, content_type = render_metered_whisper_response(
        {
            "text": "hello world",
            "duration": 1.25,
            "segments": [{"start": 0, "end": 1.25, "text": " hello world"}],
        },
        "srt",
    )

    assert body == b"1\n00:00:00,000 --> 00:00:01,250\nhello world\n"
    assert content_type == "application/x-subrip"


@pytest.mark.parametrize("operation", ["transcriptions", "translations"])
def test_raw_format_is_metered_even_for_a_deployment_alias(operation):
    payload = _multipart_payload()
    payload["model"] = "azure-audio-production"
    payload["response_format"] = "vtt"

    assert metered_whisper_response_format(payload, f"v1/audio/{operation}") == "vtt"


async def test_openai_sdk_transcription_request_is_accepted():
    app = FastAPI()

    @app.post("/v1/audio/transcriptions")
    async def transcription(request: Request):
        payload = await parse_audio_upload(request)
        sanitized = sanitized_payload_for_logging(payload)
        return JSONResponse(
            {
                "text": "hello from Logos",
                "model": sanitized["model"],
                "filename": sanitized["files"][0]["filename"],
            }
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://logos.test") as http_client:
        client = AsyncOpenAI(
            api_key="lg-test",
            base_url="http://logos.test/v1",
            http_client=http_client,
        )
        result = await client.audio.transcriptions.create(
            file=("speech.wav", b"RIFFaudio", "audio/wav"),
            model="whisper-1",
        )

    assert result.text == "hello from Logos"
    assert result.model_extra["model"] == "whisper-1"
    assert result.model_extra["filename"] == "speech.wav"


async def test_audio_upload_rejects_files_over_the_configured_limit(monkeypatch):
    monkeypatch.setattr(request_content, "MAX_AUDIO_UPLOAD_BYTES", 16)
    app = FastAPI()

    @app.post("/v1/audio/transcriptions")
    async def transcription(request: Request):
        await parse_audio_upload(request)
        return JSONResponse({"text": "unexpected"})

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://logos.test") as client:
        response = await client.post(
            "/v1/audio/transcriptions",
            data={"model": "whisper-1"},
            files={"file": ("speech.wav", b"12345678901234567", "audio/wav")},
        )

    assert response.status_code == 413
    assert "16-byte upload limit" in response.json()["detail"]


async def test_audio_file_can_exceed_the_text_field_limit():
    app = FastAPI()

    @app.post("/v1/audio/transcriptions")
    async def transcription(request: Request):
        payload = await parse_audio_upload(request)
        return JSONResponse({"size": sanitized_payload_for_logging(payload)["files"][0]["size"]})

    audio = b"a" * (request_content.MAX_AUDIO_FORM_FIELD_BYTES + 1)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://logos.test") as client:
        response = await client.post(
            "/v1/audio/transcriptions",
            data={"model": "whisper-1"},
            files={"file": ("speech.wav", audio, "audio/wav")},
        )

    assert response.status_code == 200
    assert response.json() == {"size": len(audio)}


async def test_audio_upload_closes_spooled_file_after_encoding(monkeypatch):
    captured_files = []
    original_encode = request_content._encode_form_data

    async def capture_and_encode(form):
        captured_files.extend(value for _, value in form.multi_items() if isinstance(value, UploadFile))
        return await original_encode(form)

    monkeypatch.setattr(request_content, "_encode_form_data", capture_and_encode)
    app = FastAPI()

    @app.post("/v1/audio/transcriptions")
    async def transcription(request: Request):
        await parse_audio_upload(request)
        return JSONResponse({"text": "ok"})

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://logos.test") as client:
        response = await client.post(
            "/v1/audio/transcriptions",
            data={"model": "whisper-1"},
            files={"file": ("speech.wav", b"audio", "audio/wav")},
        )

    assert response.status_code == 200
    assert len(captured_files) == 1
    assert captured_files[0].file.closed


async def test_audio_request_limit_stops_chunked_body_before_form_spooling(monkeypatch):
    monkeypatch.setattr(request_content, "MAX_AUDIO_REQUEST_BYTES", 16)
    messages = iter(
        [
            {"type": "http.request", "body": b"12345678901234567", "more_body": True},
            {"type": "http.request", "body": b"", "more_body": False},
        ]
    )

    async def receive():
        return next(messages)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/audio/transcriptions",
            "headers": [(b"content-type", b"multipart/form-data; boundary=test")],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
            "server": ("logos.test", 80),
            "scheme": "http",
        },
        receive,
    )

    with pytest.raises(HTTPException) as exc:
        await parse_audio_upload(request)

    assert exc.value.status_code == 413


async def test_chunked_audio_limit_closes_partially_spooled_file(monkeypatch):
    created_files = []
    original_spooled_file = tempfile.SpooledTemporaryFile

    def capture_spooled_file(*args, **kwargs):
        file = original_spooled_file(*args, **kwargs)
        created_files.append(file)
        return file

    monkeypatch.setattr("starlette.formparsers.SpooledTemporaryFile", capture_spooled_file)
    prefix = (
        b"--test\r\n"
        b'Content-Disposition: form-data; name="file"; filename="speech.wav"\r\n'
        b"Content-Type: audio/wav\r\n\r\n"
    )
    first_chunk = prefix + b"audio"
    second_chunk = b"more-audio\r\n--test--\r\n"
    monkeypatch.setattr(request_content, "MAX_AUDIO_REQUEST_BYTES", len(first_chunk) + 1)
    messages = iter(
        [
            {"type": "http.request", "body": first_chunk, "more_body": True},
            {"type": "http.request", "body": second_chunk, "more_body": False},
        ]
    )

    async def receive():
        return next(messages)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/audio/transcriptions",
            "headers": [(b"content-type", b"multipart/form-data; boundary=test")],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
            "server": ("logos.test", 80),
            "scheme": "http",
            "app": object(),
        },
        receive,
    )

    with pytest.raises(HTTPException) as exc:
        await parse_audio_upload(request)

    assert exc.value.status_code == 413
    assert len(created_files) == 1
    assert created_files[0].closed


def test_audio_upload_rejects_multiple_files():
    payload = _multipart_payload()
    payload[MULTIPART_PAYLOAD_KEY]["files"].append(
        {
            "field_name": "file",
            "filename": "second.wav",
            "content_type": "audio/wav",
            "content_base64": base64.b64encode(b"second").decode(),
            "size": 6,
        }
    )

    with pytest.raises(HTTPException) as exc:
        request_content._validate_audio_upload(payload)

    assert exc.value.status_code == 400

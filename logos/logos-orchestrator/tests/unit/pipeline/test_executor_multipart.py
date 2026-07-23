"""Multipart transport and non-JSON transcription responses."""

import base64

import httpx

from logos.pipeline.executor import Executor
from logos.request_content import MULTIPART_PAYLOAD_KEY


def _payload(response_format: str = "text") -> dict:
    return {
        "model": "whisper-1",
        "response_format": response_format,
        MULTIPART_PAYLOAD_KEY: {
            "fields": [["model", "whisper-1"], ["response_format", response_format]],
            "files": [
                {
                    "field_name": "file",
                    "filename": "speech.wav",
                    "content_type": "audio/wav",
                    "content_base64": base64.b64encode(b"RIFFaudio").decode(),
                    "size": 9,
                }
            ],
        },
    }


async def test_sync_executor_sends_multipart_and_preserves_plain_text(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
        assert b'name="model"' in body
        assert b"whisper-1" in body
        assert b'name="stream"' in body
        assert b"false" in body
        assert b'filename="speech.wav"' in body
        assert b"RIFFaudio" in body
        return httpx.Response(
            200,
            content=b"transcribed text",
            headers={"content-type": "text/plain; charset=utf-8"},
        )

    real_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "logos.pipeline.executor.httpx.AsyncClient",
        lambda *args, **kwargs: real_async_client(transport=transport, *args, **kwargs),
    )

    result = await Executor().execute_sync(
        "https://provider.test/v1/audio/transcriptions",
        {"Authorization": "Bearer upstream"},
        _payload(),
    )

    assert result.success
    assert result.response == "transcribed text"
    assert result.raw_body == b"transcribed text"
    assert result.content_type == "text/plain; charset=utf-8"


async def test_sync_executor_keeps_json_transcription_response(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        await request.aread()
        return httpx.Response(
            200,
            json={"text": "transcribed text", "usage": {"total_tokens": 12}},
        )

    real_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "logos.pipeline.executor.httpx.AsyncClient",
        lambda *args, **kwargs: real_async_client(transport=transport, *args, **kwargs),
    )

    result = await Executor().execute_sync(
        "https://provider.test/v1/audio/transcriptions",
        {},
        _payload("json"),
    )

    assert result.success
    assert result.response == {"text": "transcribed text", "usage": {"total_tokens": 12}}
    assert result.raw_body is None
    assert result.usage == {"total_tokens": 12}


async def test_sync_executor_still_rejects_non_json_chat_success(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        await request.aread()
        return httpx.Response(200, content=b"<html>not an API response</html>", headers={"content-type": "text/html"})

    real_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "logos.pipeline.executor.httpx.AsyncClient",
        lambda *args, **kwargs: real_async_client(transport=transport, *args, **kwargs),
    )

    result = await Executor().execute_sync(
        "https://provider.test/v1/chat/completions",
        {},
        {"model": "gpt-4o", "messages": []},
    )

    assert not result.success
    assert result.raw_body is None
    assert "Invalid JSON response" in result.error

"""First-class OpenAPI exposure for audio transcription and translation."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request

import logos as main


def test_audio_routes_are_registered_before_the_v1_catch_all():
    paths = [route.path for route in main.app.routes]

    catch_all_index = paths.index("/v1/{path:path}")
    assert paths.index("/v1/audio/transcriptions") < catch_all_index
    assert paths.index("/v1/audio/translations") < catch_all_index


def test_transcription_openapi_declares_multipart_file_and_model():
    openapi = main.app.openapi()
    operation = openapi["paths"]["/v1/audio/transcriptions"]["post"]
    schema = operation["requestBody"]["content"]["multipart/form-data"]["schema"]

    assert schema["required"] == ["file", "model"]
    assert schema["properties"]["file"] == {"type": "string", "format": "binary"}
    assert "text/plain" in operation["responses"]["200"]["content"]


def test_translation_openapi_declares_multipart_contract():
    operation = main.app.openapi()["paths"]["/v1/audio/translations"]["post"]
    properties = operation["requestBody"]["content"]["multipart/form-data"]["schema"]["properties"]

    assert operation["summary"] == "Create an English audio translation"
    assert "multipart/form-data" in operation["requestBody"]["content"]
    assert "language" not in properties
    assert "timestamp_granularities[]" not in properties
    assert "stream" not in properties


async def test_audio_authentication_happens_before_multipart_parsing(monkeypatch):
    parsed = False

    def reject_auth(_headers):
        raise HTTPException(status_code=401, detail="invalid key")

    async def parse_upload(_request):
        nonlocal parsed
        parsed = True
        return {}

    monkeypatch.setattr(main, "authenticate_api_key", reject_auth)
    monkeypatch.setattr(main, "parse_audio_upload", parse_upload)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/audio/transcriptions",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
            "server": ("logos.test", 80),
            "scheme": "http",
        }
    )

    with pytest.raises(HTTPException) as exc:
        await main.auth_parse_log(request, use_profile_auth=True)

    assert exc.value.status_code == 401
    assert not parsed


async def test_audio_job_persists_only_sanitized_request_data(monkeypatch):
    persisted = None
    payload = {
        "model": "whisper-1",
        "_logos_multipart": {
            "fields": [["model", "whisper-1"]],
            "files": [
                {
                    "field_name": "file",
                    "filename": "private.wav",
                    "content_type": "audio/wav",
                    "content_base64": "c2Vuc2l0aXZlIGF1ZGlv",
                    "size": 15,
                }
            ],
        },
    }
    auth = SimpleNamespace(
        api_key_id=7,
        team_id=8,
        user_id=9,
        environment="test",
    )

    async def fake_auth_parse_log(_request, use_profile_auth=False):
        assert use_profile_auth
        return {"authorization": "Bearer lg-secret"}, auth, payload, "127.0.0.1", None

    def fake_create_job(submission):
        nonlocal persisted
        persisted = submission
        return 42

    async def fake_process_job(*_args, **_kwargs):
        return None

    monkeypatch.setattr(main, "auth_parse_log", fake_auth_parse_log)
    monkeypatch.setattr(main.JobService, "create_job", fake_create_job)
    monkeypatch.setattr(main, "process_job", fake_process_job)
    request = SimpleNamespace(
        method="POST",
        url_for=lambda _name, **_kwargs: "http://logos.test/jobs/42",
    )

    response = await main.submit_job_request("v1/audio/transcriptions", request)

    assert response.status_code == 202
    assert persisted.headers == {"authorization": "[REDACTED]"}
    assert "_logos_multipart" not in persisted.body
    assert persisted.body["files"] == [
        {
            "field_name": "file",
            "filename": "private.wav",
            "content_type": "audio/wav",
            "size": 15,
        }
    ]

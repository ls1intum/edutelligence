"""Worker-node reconstruction of orchestrator multipart payloads."""

import base64

from logos_worker_node.request_content import MULTIPART_PAYLOAD_KEY, httpx_request_parts


def test_worker_reconstructs_multipart_request():
    payload = {
        "model": "whisper-1",
        MULTIPART_PAYLOAD_KEY: {
            "fields": [["model", "whisper-1"], ["language", "de"]],
            "files": [
                {
                    "field_name": "file",
                    "filename": "speech.webm",
                    "content_type": "audio/webm",
                    "content_base64": base64.b64encode(b"webm-audio").decode(),
                }
            ],
        },
    }

    kwargs, headers = httpx_request_parts(payload)

    assert headers == {}
    assert kwargs["files"] == [
        ("model", (None, "whisper-1")),
        ("language", (None, "de")),
        ("file", ("speech.webm", b"webm-audio", "audio/webm")),
    ]


def test_worker_keeps_json_requests_unchanged():
    payload = {"model": "gpt-4o", "messages": []}
    kwargs, headers = httpx_request_parts(payload)

    assert kwargs == {"json": payload}
    assert headers == {"Content-Type": "application/json"}

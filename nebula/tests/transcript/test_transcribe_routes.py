# tests/transcript/test_transcribe_routes.py
# pylint: disable=redefined-outer-name,unused-argument,missing-class-docstring,import-outside-toplevel

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import nebula.transcript.app as app_mod
from nebula.transcript.app import app


def _get_route(path: str, method: str) -> APIRoute:
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path == path and method.upper() in r.methods:
            return r
    raise AssertionError(f"Route {method} {path} not found")


def test_start_returns_immediately_and_enqueues(monkeypatch):
    calls = []

    async def fake_enqueue(job_id, req):
        calls.append(job_id)

    async def fake_create_job():
        return "test-job-id"

    # Neutralize real worker lifecycle inside TestClient (avoid event-loop issues)
    monkeypatch.setattr(app_mod, "start_worker", lambda: None, raising=False)

    async def _noop():
        pass

    monkeypatch.setattr(app_mod, "stop_worker", _noop, raising=False)

    # Patch the endpoint's globals so its internal `await enqueue_job(...)` hits our fake
    start_route = _get_route("/transcribe/start", "POST")
    start_route.endpoint.__globals__["enqueue_job"] = fake_enqueue
    start_route.endpoint.__globals__["create_job"] = fake_create_job

    with TestClient(app) as client:
        resp = client.post(
            "/transcribe/start",
            json={"videoUrl": "https://example.com/v.m3u8", "lectureUnitId": 123},
        )
        assert resp.status_code in (200, 202)
        jid = resp.json()["transcriptionId"]
        assert calls == [jid]


def test_status_endpoint(monkeypatch):
    async def fake_get_job_status(job_id: str):
        return {"status": "processing"}

    # Neutralize worker lifecycle
    monkeypatch.setattr(app_mod, "start_worker", lambda: None, raising=False)

    async def _noop():
        pass

    monkeypatch.setattr(app_mod, "stop_worker", _noop, raising=False)

    # Patch the endpoint's globals so its internal `get_job_status(...)` hits our fake
    status_route = _get_route("/transcribe/status/{job_id}", "GET")
    status_route.endpoint.__globals__["get_job_status"] = fake_get_job_status

    with TestClient(app) as client:
        resp = client.get("/transcribe/status/abc")
        assert resp.status_code == 200
        assert resp.json()["status"] == "processing"

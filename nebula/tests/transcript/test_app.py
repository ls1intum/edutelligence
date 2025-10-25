# tests/transcript/test_app.py
# pylint: disable=redefined-outer-name,unused-argument,missing-class-docstring,import-outside-toplevel
from fastapi.testclient import TestClient

import nebula.transcript.app as app_mod  # <-- patch the symbols the app actually uses
from nebula.transcript.app import app


def test_app_starts_worker(monkeypatch):
    started = {"val": False}

    def fake_start_worker():
        started["val"] = True

    async def fake_stop_worker():
        pass

    # Patch on the app module (lifespan calls these names inside app_mod)
    monkeypatch.setattr(app_mod, "start_worker", fake_start_worker, raising=True)
    monkeypatch.setattr(app_mod, "stop_worker", fake_stop_worker, raising=True)

    with TestClient(app) as client:
        # Startup should have called start_worker
        assert started["val"] is True
        # Basic health
        resp = client.get("/transcribe/test")
        assert resp.status_code == 200
        assert resp.json()["message"] == "Transcription service is up"

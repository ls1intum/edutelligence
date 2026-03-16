import json
from unittest.mock import AsyncMock, MagicMock

import pytest

import logos.main as main


def _make_request(body: dict | None = None, headers: dict | None = None):
    request = MagicMock()
    request.headers = headers or {"authorization": "Bearer test-key"}
    request.json = AsyncMock(return_value=body or {})
    return request


class DummyDB:
    def __init__(self, payload, status):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_ollama_vram_stats(self, logos_key, day, bucket_seconds=5):
        assert logos_key == "test-key"
        assert day == "2026-03-16"
        assert bucket_seconds == 5
        return self.payload, self.status


@pytest.mark.asyncio
async def test_get_ollama_vram_stats_returns_empty_payload_for_no_data(monkeypatch):
    monkeypatch.setattr(main, "authenticate_logos_key", lambda headers: ("test-key", None))
    monkeypatch.setattr(main, "DBManager", lambda: DummyDB({"providers": []}, 200))

    response = await main.get_ollama_vram_stats(
        _make_request(body={"day": "2026-03-16"})
    )

    assert response.status_code == 200
    assert json.loads(response.body) == {"providers": []}

# tests/transcript/test_transcription_whisper.py
# pylint: disable=redefined-outer-name,unused-argument,missing-class-docstring,import-outside-toplevel

import pytest

import nebula.transcript.whisper_utils as wu

# Functions under test
from nebula.transcript.whisper_utils import transcribe_audio_chunks

# ---- Global speed-ups for this file -------------------------------------------------


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    """
    Make all retry/backoff logic instant for fast tests.
    We patch attributes only if they exist; and always nuke time.sleep.
    """
    for name, value in {
        "MAX_RETRIES": 2,
        "RETRY_BASE_DELAY": 0.0,
        "RETRY_JITTER": 0.0,
        "RETRY_MAX_DELAY": 0.0,
        "BACKOFF_CAP": 0.0,
    }.items():
        if hasattr(wu, name):
            monkeypatch.setattr(wu, name, value, raising=True)

    if hasattr(wu, "time"):
        monkeypatch.setattr(wu.time, "sleep", lambda s: None, raising=True)


# ---- Test fixtures ------------------------------------------------------------------


@pytest.fixture()
def fake_chunks(tmp_path, monkeypatch):
    """
    Create two tiny wav "chunks" and force the code under test to use them.
    Also stub get_audio_duration to 3.0s so the second chunk’s segments are offset by >= 3.0.
    """
    c1 = tmp_path / "c1.wav"
    c2 = tmp_path / "c2.wav"
    c1.write_bytes(b"\x00" * 10)
    c2.write_bytes(b"\x00" * 10)

    monkeypatch.setattr(
        wu,
        "split_audio_ffmpeg",
        lambda audio_path, out_dir, chunk_duration=180: [str(c1), str(c2)],
        raising=True,
    )
    monkeypatch.setattr(wu, "get_audio_duration", lambda p: 3.0, raising=True)

    return [str(c1), str(c2)]


@pytest.fixture()
def llm_config_openai(monkeypatch):
    """Make OpenAI path use a deterministic config."""
    config = {
        "type": "openai_whisper",
        "api_key": "sk-test",  # pragma: allowlist secret
        "model": "whisper-1",
    }
    monkeypatch.setattr(
        wu,
        "load_llm_config",
        lambda *args, **kwargs: config,
        raising=True,
    )
    return config


@pytest.fixture()
def llm_config_azure(monkeypatch):
    """Make Azure path use a deterministic config."""
    config = {
        "type": "azure_whisper",
        "api_key": "az-key",  # pragma: allowlist secret
        "endpoint": "https://example.azure.com",
        "api_version": "2024-06-01",
    }
    monkeypatch.setattr(
        wu,
        "load_llm_config",
        lambda *args, **kwargs: config,
        raising=True,
    )
    return config


# ---- Helpers -----------------------------------------------------------------------


def _mock_requests_sequence(monkeypatch, seq):
    """
    Patch requests.post used inside whisper_utils to return a sequence.

    Each item in `seq` may be:
      - {"status_code": 429}
      - {"status_code": 200, "json": {...}}
    The last item is reused for any extra calls.
    """
    calls = {"i": 0}

    class MockResp:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = "err"

        def raise_for_status(self):
            if self.status_code >= 400 and self.status_code != 429:
                raise RuntimeError("HTTP error")

        def json(self):
            return self._payload

    def mock_post(url=None, headers=None, files=None, data=None, timeout=None):
        i = calls["i"]
        calls["i"] += 1
        spec = seq[min(i, len(seq) - 1)]
        return MockResp(spec["status_code"], spec.get("json"))

    monkeypatch.setattr(wu.requests, "post", mock_post, raising=True)


# ---- Tests -------------------------------------------------------------------------


def test_openai_transcribe_happy_path(
    tmp_path, fake_chunks, llm_config_openai, monkeypatch
):
    _mock_requests_sequence(
        monkeypatch,
        [
            {"status_code": 429},
            {
                "status_code": 200,
                "json": {"segments": [{"start": 0.0, "end": 1.2, "text": "Hello"}]},
            },
            {
                "status_code": 200,
                "json": {"segments": [{"start": 0.0, "end": 0.8, "text": "World"}]},
            },
        ],
    )

    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"\x00" * 100)

    out = transcribe_audio_chunks(str(audio_path), llm_config_openai)
    assert "segments" in out
    texts = [s["text"] for s in out["segments"]]
    assert texts == ["Hello", "World"]
    assert out["segments"][1]["start"] >= 3.0  # offset from second chunk


def test_azure_transcribe_happy_path(
    tmp_path, fake_chunks, llm_config_azure, monkeypatch
):
    _mock_requests_sequence(
        monkeypatch,
        [
            {
                "status_code": 200,
                "json": {"segments": [{"start": 0.2, "end": 0.7, "text": "Foo"}]},
            },
            {
                "status_code": 200,
                "json": {"segments": [{"start": 0.1, "end": 0.5, "text": "Bar"}]},
            },
        ],
    )

    audio_path = tmp_path / "a.wav"
    audio_path.write_bytes(b"\x00" * 10)

    out = transcribe_audio_chunks(str(audio_path), llm_config_azure)
    texts = [s["text"] for s in out["segments"]]
    assert texts == ["Foo", "Bar"]
    assert out["segments"][1]["start"] >= 3.0


def test_openai_transcribe_max_retries_exhausted(
    tmp_path, fake_chunks, llm_config_openai, monkeypatch
):
    _mock_requests_sequence(monkeypatch, [{"status_code": 429}])

    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"\x00" * 10)

    with pytest.raises(RuntimeError):
        transcribe_audio_chunks(str(audio_path), llm_config_openai)


def test_get_audio_duration(monkeypatch):
    def mock_probe(probe_path):
        return {"format": {"duration": "12.34"}}

    monkeypatch.setattr(wu.ffmpeg, "probe", mock_probe, raising=True)
    assert wu.get_audio_duration("whatever.wav") == 12.34

from unittest.mock import patch

from fastapi.testclient import TestClient

from nebula.transcript.app import app

client = TestClient(app)


def test_home(authorized_headers):
    response = client.get("/", headers=authorized_headers)
    assert response.status_code == 200
    assert response.json() == {"message": "FastAPI server is running!"}


@patch("nebula.transcript.app.download_video")
@patch("nebula.transcript.app.extract_audio")
@patch("nebula.transcript.app.transcribe_with_azure_whisper")
@patch("nebula.transcript.app.extract_frames_at_timestamps")
@patch("nebula.transcript.app.ask_gpt_for_slide_number")
@patch("nebula.transcript.app.align_slides_with_segments")
def test_start_transcribe_success(
    mock_align,
    mock_gpt,
    mock_frames,
    mock_transcribe,
    *_,
    authorized_headers,
):
    mock_transcribe.return_value = {
        "segments": [{"start": 0, "end": 1, "text": "Hello"}],
        "language": "en",
    }
    mock_frames.return_value = [(0, "dummy_b64")]
    mock_gpt.return_value = 1
    mock_align.return_value = [
        {"startTime": 0, "endTime": 1, "text": "Hello", "slideNumber": 1}
    ]

    payload = {"videoUrl": "http://example.com/video.mp4", "lectureUnitId": 42}
    response = client.post(
        "/start-transcribe", json=payload, headers=authorized_headers
    )

    assert response.status_code == 200
    assert response.json()["lectureUnitId"] == 42
    assert len(response.json()["segments"]) == 1


def test_start_transcribe_missing_video_url(authorized_headers):
    response = client.post(
        "/start-transcribe", json={"lectureUnitId": 42}, headers=authorized_headers
    )
    assert response.status_code == 422


@patch("nebula.transcript.app.download_video")
@patch("nebula.transcript.app.extract_audio")
@patch("nebula.transcript.app.transcribe_with_azure_whisper")
@patch("nebula.transcript.app.extract_frames_at_timestamps")
@patch("nebula.transcript.app.ask_gpt_for_slide_number")
@patch("nebula.transcript.app.align_slides_with_segments")
def test_start_transcribe_gpt_returns_none(
    mock_align,
    mock_gpt,
    mock_frames,
    mock_transcribe,
    *_,
    authorized_headers,
):
    mock_transcribe.return_value = {
        "segments": [{"start": 0, "end": 1, "text": "No slide"}],
        "language": "en",
    }
    mock_frames.return_value = [(0, "dummy_b64")]
    mock_gpt.return_value = None
    mock_align.return_value = [
        {"startTime": 0, "endTime": 1, "text": "No slide", "slideNumber": 0}
    ]

    payload = {"videoUrl": "http://example.com/video.mp4", "lectureUnitId": 42}
    response = client.post(
        "/start-transcribe", json=payload, headers=authorized_headers
    )

    assert response.status_code == 200
    assert isinstance(response.json()["segments"][0]["slideNumber"], int)


@patch("nebula.transcript.app.download_video")
@patch("nebula.transcript.app.extract_audio")
@patch(
    "nebula.transcript.app.transcribe_with_azure_whisper",
    side_effect=RuntimeError("Whisper failed"),
)
def test_start_transcribe_whisper_failure(*_, authorized_headers):
    payload = {"videoUrl": "http://example.com/video.mp4", "lectureUnitId": 42}
    response = client.post(
        "/start-transcribe", json=payload, headers=authorized_headers
    )
    assert response.status_code == 500
    assert "Whisper failed" in response.json()["detail"]


@patch("nebula.transcript.app.download_video")
@patch("nebula.transcript.app.extract_audio")
@patch(
    "nebula.transcript.app.transcribe_with_azure_whisper", side_effect=Exception("Boom")
)
@patch("os.remove")
def test_start_transcribe_cleanup_on_failure(mock_remove, *_, authorized_headers):
    payload = {"videoUrl": "http://example.com/video.mp4", "lectureUnitId": 42}
    response = client.post(
        "/start-transcribe", json=payload, headers=authorized_headers
    )
    assert response.status_code == 500
    assert mock_remove.called


def test_start_transcribe_invalid_schema(authorized_headers):
    payload = {"videoUrl": 123, "lectureUnitId": "abc"}
    response = client.post(
        "/start-transcribe", json=payload, headers=authorized_headers
    )
    assert response.status_code == 422


def test_start_transcribe_unauthorized():
    payload = {"videoUrl": "http://example.com/video.mp4", "lectureUnitId": 42}
    response = client.post("/start-transcribe", json=payload)  # No auth header
    assert response.status_code == 401

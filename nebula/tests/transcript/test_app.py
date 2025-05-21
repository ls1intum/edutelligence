from unittest.mock import patch

from fastapi.testclient import TestClient

from nebula.transcript.app import app
from nebula.transcript.jobs import create_job, save_job_result

client = TestClient(app)


def test_home():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "message": "FastAPI Nebula transcription service is running"
    }


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
    mock_audio,  # pylint: disable=unused-argument
    mock_download,  # pylint: disable=unused-argument
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
    response = client.post("/start-transcribe", json=payload)

    assert response.status_code == 200
    assert "transcriptionId" in response.json()
    assert response.json()["status"] == "processing"


def test_get_status_done():
    job_id = create_job()
    save_job_result(
        job_id,
        {
            "lectureUnitId": 42,
            "language": "en",
            "segments": [
                {"startTime": 0, "endTime": 1, "text": "test", "slideNumber": 1}
            ],
        },
    )

    response = client.get(f"/status/{job_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "done"
    assert response.json()["lectureUnitId"] == 42


def test_start_transcribe_invalid_schema():
    payload = {"videoUrl": 123, "lectureUnitId": "abc"}
    response = client.post("/start-transcribe", json=payload)
    assert response.status_code == 422

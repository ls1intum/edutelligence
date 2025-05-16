import pytest
from unittest.mock import patch, MagicMock, mock_open
from nebula.transcript.whisper_utils import transcribe_with_azure_whisper


@patch("builtins.open", new_callable=mock_open, read_data=b"dummy audio")
@patch("nebula.transcript.whisper_utils.get_audio_duration", return_value=5.0)
@patch("nebula.transcript.whisper_utils.requests.post")
@patch("nebula.transcript.whisper_utils.split_audio_ffmpeg")
@patch("nebula.transcript.whisper_utils.load_llm_config")
def test_transcribe_with_azure_whisper_success(
    mock_config, mock_split, mock_post, mock_duration, mock_file
):
    # Mock Azure config
    mock_config.return_value = {
        "api_key": "dummy",
        "endpoint": "https://dummy.azure.com",
        "api_version": "2024-06-01",
    }

    # Simulate audio split
    mock_split.return_value = ["test_chunk.wav"]

    # Simulate Whisper response
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "segments": [{"start": 0, "end": 2, "text": "Hello"}]
    }
    mock_response.raise_for_status.return_value = None
    mock_post.return_value = mock_response

    result = transcribe_with_azure_whisper("dummy.wav")

    assert "segments" in result
    assert result["segments"][0]["text"] == "Hello"
    assert result["segments"][0]["start"] == 0
    assert result["segments"][0]["end"] == 2


@patch("builtins.open", new_callable=mock_open, read_data=b"dummy audio")
@patch("nebula.transcript.whisper_utils.requests.post", side_effect=Exception("Boom"))
@patch("nebula.transcript.whisper_utils.split_audio_ffmpeg")
@patch("nebula.transcript.whisper_utils.load_llm_config")
def test_transcribe_with_azure_whisper_failure(
    mock_config, mock_split, mock_post, mock_file
):
    mock_config.return_value = {
        "api_key": "dummy",
        "endpoint": "https://dummy.azure.com",
        "api_version": "2024-06-01",
    }
    mock_split.return_value = ["test_chunk.wav"]

    with pytest.raises(Exception) as excinfo:
        transcribe_with_azure_whisper("dummy.wav")

    assert "Boom" in str(excinfo.value)

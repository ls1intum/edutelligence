import pytest
from unittest.mock import patch, MagicMock
from nebula.transcript.video_utils import extract_audio


@patch("subprocess.run")
def test_extract_audio_success(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    extract_audio("input.mp4", "output.wav")
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert "ffmpeg" in args[0]
    assert "input.mp4" in args


@patch("subprocess.run")
def test_extract_audio_failure(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stderr="error")
    with pytest.raises(RuntimeError, match="FFmpeg audio extraction failed"):
        extract_audio("bad.mp4", "fail.wav")

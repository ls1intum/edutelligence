import os
from unittest.mock import MagicMock, patch

import pytest
import yt_dlp

from iris.pipeline.transcription.utils.youtube_utils import (
    YouTubeDownloadError,
    _validate_youtube_video,
    download_youtube_audio,
)


class TestValidateYouTubeVideo:
    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    def test_valid_public_video(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {"id": "abc123", "duration": 600}
        mock_ydl_class.return_value = mock_ydl

        info = _validate_youtube_video("https://youtube.com/watch?v=abc123")
        assert info["id"] == "abc123"
        assert info["duration"] == 600

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    def test_private_video_raises(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = yt_dlp.utils.DownloadError(
            "Private video. Sign in"
        )
        mock_ydl_class.return_value = mock_ydl

        with pytest.raises(YouTubeDownloadError, match="private"):
            _validate_youtube_video("https://youtube.com/watch?v=PRIVATE")

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    def test_video_too_long_raises(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "id": "long",
            "duration": 7 * 60 * 60,
        }
        mock_ydl_class.return_value = mock_ydl

        with pytest.raises(YouTubeDownloadError, match="exceeds maximum"):
            _validate_youtube_video("https://youtube.com/watch?v=long")

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    def test_unavailable_video_raises(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = yt_dlp.utils.DownloadError(
            "Video not available"
        )
        mock_ydl_class.return_value = mock_ydl

        with pytest.raises(YouTubeDownloadError, match="not available"):
            _validate_youtube_video("https://youtube.com/watch?v=GONE")

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    def test_live_stream_raises(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {"id": "live", "duration": None}
        mock_ydl_class.return_value = mock_ydl

        with pytest.raises(YouTubeDownloadError, match="Live streams"):
            _validate_youtube_video("https://youtube.com/watch?v=live")

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    def test_zero_duration_raises(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {"id": "zero", "duration": 0}
        mock_ydl_class.return_value = mock_ydl

        with pytest.raises(YouTubeDownloadError, match="Live streams"):
            _validate_youtube_video("https://youtube.com/watch?v=zero")


class TestDownloadYouTubeAudio:
    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    @patch("iris.pipeline.transcription.utils.youtube_utils._validate_youtube_video")
    def test_successful_download(self, mock_validate, mock_ydl_class, tmp_path):
        mock_validate.return_value = {"id": "test123", "duration": 60}

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl_class.return_value = mock_ydl

        audio_path = str(tmp_path / "output.mp3")
        # Simulate yt-dlp creating the output file at the expected path
        (tmp_path / "output.mp3").write_bytes(b"fake mp3 data")

        download_youtube_audio(
            "https://youtube.com/watch?v=test123",
            audio_path,
            lecture_unit_id=42,
        )

        assert os.path.exists(audio_path)

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    @patch("iris.pipeline.transcription.utils.youtube_utils._validate_youtube_video")
    def test_download_failure_raises_runtime_error(
        self, mock_validate, mock_ydl_class
    ):
        mock_validate.return_value = {"id": "fail", "duration": 60}

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.download.side_effect = yt_dlp.utils.DownloadError(
            "Network error"
        )
        mock_ydl_class.return_value = mock_ydl

        with pytest.raises(RuntimeError, match="Failed to download"):
            download_youtube_audio(
                "https://youtube.com/watch?v=fail",
                "/tmp/fail.mp3",
            )

    @patch("iris.pipeline.transcription.utils.youtube_utils._validate_youtube_video")
    def test_validation_error_raises_runtime_error(self, mock_validate):
        mock_validate.side_effect = YouTubeDownloadError("Video is private")

        with pytest.raises(RuntimeError, match="Video is private"):
            download_youtube_audio(
                "https://youtube.com/watch?v=private",
                "/tmp/private.mp3",
            )

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    @patch("iris.pipeline.transcription.utils.youtube_utils._validate_youtube_video")
    def test_missing_output_file_raises_runtime_error(
        self, mock_validate, mock_ydl_class, tmp_path
    ):
        mock_validate.return_value = {"id": "missing", "duration": 60}

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl_class.return_value = mock_ydl

        # Don't create the output file — simulates yt-dlp silently failing
        audio_path = str(tmp_path / "missing.mp3")

        with pytest.raises(RuntimeError, match="not found after download"):
            download_youtube_audio(
                "https://youtube.com/watch?v=missing",
                audio_path,
            )

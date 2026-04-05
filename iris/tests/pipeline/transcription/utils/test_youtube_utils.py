"""Tests for YouTube audio download utilities."""

import os
from unittest.mock import MagicMock, patch

import pytest
import yt_dlp

from iris.pipeline.transcription.utils.youtube_utils import (
    MAX_VIDEO_DURATION_SECONDS,
    YouTubeDownloadError,
    _validate_youtube_video,
    download_youtube_audio,
)


def _mock_ydl(extract_info_return=None, extract_info_side_effect=None):
    """Create a mock YoutubeDL context manager."""
    mock = MagicMock()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    if extract_info_side_effect:
        mock.extract_info.side_effect = extract_info_side_effect
    elif extract_info_return is not None:
        mock.extract_info.return_value = extract_info_return
    return mock


class TestValidateYouTubeVideo:
    """Tests for YouTube video validation (accessibility, duration limits)."""

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    def test_valid_public_video(self, mock_ydl_class):
        mock_ydl_class.return_value = _mock_ydl(
            extract_info_return={"id": "abc123", "duration": 600}
        )

        info = _validate_youtube_video("https://youtube.com/watch?v=abc123")

        assert info == {"id": "abc123", "duration": 600}
        # Verify extract_info was called with download=False
        mock_ydl_class.return_value.extract_info.assert_called_once_with(
            "https://youtube.com/watch?v=abc123", download=False
        )

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    def test_returns_only_id_and_duration(self, mock_ydl_class):
        mock_ydl_class.return_value = _mock_ydl(
            extract_info_return={
                "id": "xyz",
                "duration": 120,
                "title": "Extra field",
                "formats": [],
                "thumbnails": [],
            }
        )

        info = _validate_youtube_video("https://youtube.com/watch?v=xyz")
        assert set(info.keys()) == {"id", "duration"}

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    def test_missing_id_defaults_to_unknown(self, mock_ydl_class):
        mock_ydl_class.return_value = _mock_ydl(extract_info_return={"duration": 300})

        info = _validate_youtube_video("https://youtube.com/watch?v=noid")
        assert info["id"] == "unknown"
        assert info["duration"] == 300

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    def test_private_video_raises(self, mock_ydl_class):
        mock_ydl_class.return_value = _mock_ydl(
            extract_info_side_effect=yt_dlp.utils.DownloadError(
                "Private video. Sign in"
            )
        )

        with pytest.raises(YouTubeDownloadError, match="private"):
            _validate_youtube_video("https://youtube.com/watch?v=PRIVATE")

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    def test_sign_in_required_raises(self, mock_ydl_class):
        mock_ydl_class.return_value = _mock_ydl(
            extract_info_side_effect=yt_dlp.utils.DownloadError(
                "Sign in to confirm your age"
            )
        )

        with pytest.raises(YouTubeDownloadError, match="private"):
            _validate_youtube_video("https://youtube.com/watch?v=AGE")

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    def test_video_too_long_raises(self, mock_ydl_class):
        over_limit = MAX_VIDEO_DURATION_SECONDS + 1
        mock_ydl_class.return_value = _mock_ydl(
            extract_info_return={"id": "long", "duration": over_limit}
        )

        with pytest.raises(YouTubeDownloadError, match="exceeds maximum"):
            _validate_youtube_video("https://youtube.com/watch?v=long")

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    def test_video_at_exact_max_duration_passes(self, mock_ydl_class):
        mock_ydl_class.return_value = _mock_ydl(
            extract_info_return={"id": "exact", "duration": MAX_VIDEO_DURATION_SECONDS}
        )

        info = _validate_youtube_video("https://youtube.com/watch?v=exact")
        assert info["duration"] == MAX_VIDEO_DURATION_SECONDS

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    def test_unavailable_video_raises(self, mock_ydl_class):
        mock_ydl_class.return_value = _mock_ydl(
            extract_info_side_effect=yt_dlp.utils.DownloadError("Video not available")
        )

        with pytest.raises(YouTubeDownloadError, match="not available"):
            _validate_youtube_video("https://youtube.com/watch?v=GONE")

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    def test_generic_download_error_raises(self, mock_ydl_class):
        mock_ydl_class.return_value = _mock_ydl(
            extract_info_side_effect=yt_dlp.utils.DownloadError(
                "Some unexpected error from yt-dlp"
            )
        )

        with pytest.raises(
            YouTubeDownloadError, match="Failed to access YouTube video"
        ):
            _validate_youtube_video("https://youtube.com/watch?v=ERR")

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    def test_live_stream_none_duration_raises(self, mock_ydl_class):
        mock_ydl_class.return_value = _mock_ydl(
            extract_info_return={"id": "live", "duration": None}
        )

        with pytest.raises(YouTubeDownloadError, match="Live streams"):
            _validate_youtube_video("https://youtube.com/watch?v=live")

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    def test_zero_duration_raises(self, mock_ydl_class):
        mock_ydl_class.return_value = _mock_ydl(
            extract_info_return={"id": "zero", "duration": 0}
        )

        with pytest.raises(YouTubeDownloadError, match="Live streams"):
            _validate_youtube_video("https://youtube.com/watch?v=zero")

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    def test_negative_duration_raises(self, mock_ydl_class):
        mock_ydl_class.return_value = _mock_ydl(
            extract_info_return={"id": "neg", "duration": -1}
        )

        with pytest.raises(YouTubeDownloadError, match="Live streams"):
            _validate_youtube_video("https://youtube.com/watch?v=neg")


class TestDownloadYouTubeAudio:
    """Tests for YouTube audio download with yt-dlp."""

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    @patch("iris.pipeline.transcription.utils.youtube_utils._validate_youtube_video")
    def test_successful_download(self, mock_validate, mock_ydl_class, tmp_path):
        mock_validate.return_value = {"id": "test123", "duration": 60}

        audio_path = str(tmp_path / "output.mp3")

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.download.side_effect = lambda urls: (
            tmp_path / "output.mp3"
        ).write_bytes(b"fake mp3 data")
        mock_ydl_class.return_value = mock_ydl

        download_youtube_audio(
            "https://youtube.com/watch?v=test123",
            audio_path,
            lecture_unit_id=42,
            timeout=600,
        )

        assert os.path.exists(audio_path)
        # Verify validate was called with the correct URL
        mock_validate.assert_called_once_with("https://youtube.com/watch?v=test123")
        # Verify yt-dlp received correct options
        ydl_opts = mock_ydl_class.call_args[0][0]
        assert ydl_opts["socket_timeout"] == 600
        assert ydl_opts["format"] == "bestaudio/best"
        assert ydl_opts["noplaylist"] is True
        assert ydl_opts["retries"] == 3
        # Verify yt-dlp download was called with the URL
        mock_ydl.download.assert_called_once_with(
            ["https://youtube.com/watch?v=test123"]
        )

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    @patch("iris.pipeline.transcription.utils.youtube_utils._validate_youtube_video")
    def test_output_template_uses_audio_path_basename(
        self, mock_validate, mock_ydl_class, tmp_path
    ):
        mock_validate.return_value = {"id": "vid456", "duration": 60}

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.download.side_effect = lambda urls: (
            tmp_path / "my-uuid.mp3"
        ).write_bytes(b"data")
        mock_ydl_class.return_value = mock_ydl

        audio_path = str(tmp_path / "my-uuid.mp3")
        download_youtube_audio("https://youtube.com/watch?v=vid456", audio_path)

        ydl_opts = mock_ydl_class.call_args[0][0]
        # Template should use audio_path basename, NOT video_id
        assert "my-uuid" in ydl_opts["outtmpl"]
        assert "vid456" not in ydl_opts["outtmpl"]

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    @patch("iris.pipeline.transcription.utils.youtube_utils._validate_youtube_video")
    def test_default_timeout(self, mock_validate, mock_ydl_class, tmp_path):
        mock_validate.return_value = {"id": "t", "duration": 10}

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.download.side_effect = lambda urls: (tmp_path / "out.mp3").write_bytes(
            b"data"
        )
        mock_ydl_class.return_value = mock_ydl

        download_youtube_audio(
            "https://youtube.com/watch?v=t", str(tmp_path / "out.mp3")
        )

        ydl_opts = mock_ydl_class.call_args[0][0]
        assert ydl_opts["socket_timeout"] == 3600  # Default

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    @patch("iris.pipeline.transcription.utils.youtube_utils._validate_youtube_video")
    def test_download_failure_raises_runtime_error(self, mock_validate, mock_ydl_class):
        mock_validate.return_value = {"id": "fail", "duration": 60}

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.download.side_effect = yt_dlp.utils.DownloadError("Network error")
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

    @patch("iris.pipeline.transcription.utils.youtube_utils._validate_youtube_video")
    def test_validation_error_chains_original_exception(self, mock_validate):
        original = YouTubeDownloadError("Original cause")
        mock_validate.side_effect = original

        with pytest.raises(RuntimeError) as exc_info:
            download_youtube_audio("https://youtube.com/watch?v=x", "/tmp/x.mp3")

        assert exc_info.value.__cause__ is original

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

        audio_path = str(tmp_path / "missing.mp3")

        with pytest.raises(RuntimeError, match="not found after download"):
            download_youtube_audio(
                "https://youtube.com/watch?v=missing",
                audio_path,
            )

    @patch("iris.pipeline.transcription.utils.youtube_utils.yt_dlp.YoutubeDL")
    @patch("iris.pipeline.transcription.utils.youtube_utils._validate_youtube_video")
    def test_postprocessor_config(self, mock_validate, mock_ydl_class, tmp_path):
        mock_validate.return_value = {"id": "pp", "duration": 10}

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.download.side_effect = lambda urls: (tmp_path / "pp.mp3").write_bytes(
            b"data"
        )
        mock_ydl_class.return_value = mock_ydl

        download_youtube_audio(
            "https://youtube.com/watch?v=pp", str(tmp_path / "pp.mp3")
        )

        ydl_opts = mock_ydl_class.call_args[0][0]
        pp = ydl_opts["postprocessors"]
        assert len(pp) == 1
        assert pp[0]["key"] == "FFmpegExtractAudio"
        assert pp[0]["preferredcodec"] == "mp3"

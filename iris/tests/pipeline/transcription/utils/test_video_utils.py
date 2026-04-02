"""Tests for FFmpeg video download and audio extraction utilities."""

import subprocess
from unittest.mock import patch

import pytest

from iris.pipeline.transcription.utils.video_utils import download_video, extract_audio


class TestDownloadVideo:
    @patch("iris.pipeline.transcription.utils.video_utils.subprocess.run")
    def test_successful_download(self, mock_run):
        download_video(
            "https://example.com/stream.m3u8",
            "/tmp/video.mp4",
            lecture_unit_id=1,
            timeout=1800,
        )

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "https://example.com/stream.m3u8" in cmd
        assert "/tmp/video.mp4" in cmd
        assert mock_run.call_args[1]["shell"] is False
        assert mock_run.call_args[1]["check"] is True
        assert mock_run.call_args[1]["timeout"] == 1800

    @patch("iris.pipeline.transcription.utils.video_utils.subprocess.run")
    def test_protocol_whitelist_excludes_file(self, mock_run):
        download_video("https://example.com/v.m3u8", "/tmp/v.mp4")

        cmd = mock_run.call_args[0][0]
        pw_idx = cmd.index("-protocol_whitelist")
        whitelist = cmd[pw_idx + 1]
        assert "file" not in whitelist
        assert "http" in whitelist
        assert "https" in whitelist

    @patch("iris.pipeline.transcription.utils.video_utils.subprocess.run")
    def test_timeout_raises_runtime_error(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ffmpeg", timeout=60)

        with pytest.raises(RuntimeError, match="timed out"):
            download_video("https://example.com/v.m3u8", "/tmp/v.mp4", timeout=60)

    @patch("iris.pipeline.transcription.utils.video_utils.subprocess.run")
    def test_ffmpeg_failure_raises_runtime_error(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "ffmpeg", stderr="connection refused"
        )

        with pytest.raises(RuntimeError, match="FFmpeg download failed") as exc_info:
            download_video("https://example.com/v.m3u8", "/tmp/v.mp4")
        assert "connection refused" in str(exc_info.value)

    @patch("iris.pipeline.transcription.utils.video_utils.subprocess.run")
    def test_default_timeout_is_3600(self, mock_run):
        download_video("https://example.com/v.m3u8", "/tmp/v.mp4")

        assert mock_run.call_args[1]["timeout"] == 3600


class TestExtractAudio:
    @patch("iris.pipeline.transcription.utils.video_utils.subprocess.run")
    def test_successful_extraction(self, mock_run):
        extract_audio(
            "/tmp/video.mp4",
            "/tmp/audio.mp3",
            lecture_unit_id=5,
            timeout=300,
        )

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "/tmp/video.mp4" in cmd
        assert "/tmp/audio.mp3" in cmd
        assert mock_run.call_args[1]["shell"] is False
        assert mock_run.call_args[1]["check"] is True
        assert mock_run.call_args[1]["timeout"] == 300

    @patch("iris.pipeline.transcription.utils.video_utils.subprocess.run")
    def test_extracts_audio_stream_only(self, mock_run):
        extract_audio("/tmp/video.mp4", "/tmp/audio.mp3")

        cmd = mock_run.call_args[0][0]
        assert "-map" in cmd
        assert cmd[cmd.index("-map") + 1] == "a"

    @patch("iris.pipeline.transcription.utils.video_utils.subprocess.run")
    def test_best_quality_audio(self, mock_run):
        extract_audio("/tmp/video.mp4", "/tmp/audio.mp3")

        cmd = mock_run.call_args[0][0]
        assert "-q:a" in cmd
        assert cmd[cmd.index("-q:a") + 1] == "0"

    @patch("iris.pipeline.transcription.utils.video_utils.subprocess.run")
    def test_timeout_raises_runtime_error(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ffmpeg", timeout=120)

        with pytest.raises(RuntimeError, match="timed out"):
            extract_audio("/tmp/v.mp4", "/tmp/a.mp3", timeout=120)

    @patch("iris.pipeline.transcription.utils.video_utils.subprocess.run")
    def test_ffmpeg_failure_raises_runtime_error(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "ffmpeg", stderr="invalid codec"
        )

        with pytest.raises(RuntimeError, match="audio extraction failed") as exc_info:
            extract_audio("/tmp/v.mp4", "/tmp/a.mp3")
        assert "invalid codec" in str(exc_info.value)

    @patch("iris.pipeline.transcription.utils.video_utils.subprocess.run")
    def test_default_timeout_is_600(self, mock_run):
        extract_audio("/tmp/video.mp4", "/tmp/audio.mp3")

        assert mock_run.call_args[1]["timeout"] == 600

    @patch("iris.pipeline.transcription.utils.video_utils.subprocess.run")
    def test_overwrites_existing_output(self, mock_run):
        extract_audio("/tmp/video.mp4", "/tmp/audio.mp3")

        cmd = mock_run.call_args[0][0]
        assert "-y" in cmd

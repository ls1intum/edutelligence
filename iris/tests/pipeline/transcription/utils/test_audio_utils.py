"""Tests for audio splitting utilities."""

import os
import subprocess
from unittest.mock import patch

import pytest

from iris.pipeline.transcription.utils.audio_utils import split_audio_ffmpeg


def _ffmpeg_creates_chunks(tmp_path, filenames):
    """Return a side_effect that simulates FFmpeg creating chunk files."""

    def side_effect(*_args, **_kwargs):
        for name in filenames:
            (tmp_path / name).write_bytes(b"chunk data")

    return side_effect


class TestSplitAudioFfmpeg:
    """Tests for FFmpeg audio splitting into chunks."""
    def test_successful_split_returns_sorted_mp3_paths(self, tmp_path):
        output_dir = str(tmp_path / "chunks")

        with patch(
            "iris.pipeline.transcription.utils.audio_utils.subprocess.run",
            side_effect=_ffmpeg_creates_chunks(
                tmp_path / "chunks",
                ["audio_000.mp3", "audio_002.mp3", "audio_001.mp3"],
            ),
        ):
            result = split_audio_ffmpeg(
                "/fake/audio.mp3", output_dir, chunk_duration=900
            )

        assert len(result) == 3
        assert all(p.endswith(".mp3") for p in result)
        assert result == sorted(result)
        assert all(os.path.isabs(p) or os.path.exists(p) for p in result)

    def test_ffmpeg_failure_raises_runtime_error(self, tmp_path):
        output_dir = str(tmp_path / "chunks")

        with patch(
            "iris.pipeline.transcription.utils.audio_utils.subprocess.run",
            side_effect=subprocess.CalledProcessError(
                1, "ffmpeg", stderr="encoding error"
            ),
        ):
            with pytest.raises(
                RuntimeError, match="FFmpeg audio split failed"
            ) as exc_info:
                split_audio_ffmpeg("/fake/audio.mp3", output_dir)
            assert "encoding error" in str(exc_info.value)

    def test_no_chunks_generated_raises_runtime_error(self, tmp_path):
        output_dir = str(tmp_path / "chunks")

        with patch("iris.pipeline.transcription.utils.audio_utils.subprocess.run"):
            with pytest.raises(RuntimeError, match="No chunks were generated"):
                split_audio_ffmpeg("/fake/audio.mp3", output_dir)

    def test_creates_output_dir_if_missing(self, tmp_path):
        output_dir = str(tmp_path / "new_dir" / "chunks")
        assert not os.path.exists(output_dir)

        with patch(
            "iris.pipeline.transcription.utils.audio_utils.subprocess.run",
            side_effect=_ffmpeg_creates_chunks(
                tmp_path / "new_dir" / "chunks", ["audio_000.mp3"]
            ),
        ):
            result = split_audio_ffmpeg("/fake/audio.mp3", output_dir)

        assert os.path.isdir(output_dir)
        assert len(result) == 1

    def test_cleans_old_mp3_before_splitting(self, tmp_path):
        output_dir = str(tmp_path / "chunks")
        os.makedirs(output_dir)
        old_chunk = tmp_path / "chunks" / "stale_000.mp3"
        old_chunk.write_bytes(b"old data")

        with patch(
            "iris.pipeline.transcription.utils.audio_utils.subprocess.run",
            side_effect=_ffmpeg_creates_chunks(tmp_path / "chunks", ["fresh_000.mp3"]),
        ):
            result = split_audio_ffmpeg("/fake/audio.mp3", output_dir)

        assert not old_chunk.exists()
        assert len(result) == 1
        assert result[0].endswith("fresh_000.mp3")

    def test_non_mp3_files_not_cleaned(self, tmp_path):
        output_dir = str(tmp_path / "chunks")
        os.makedirs(output_dir)
        txt_file = tmp_path / "chunks" / "notes.txt"
        txt_file.write_text("keep me")

        with patch(
            "iris.pipeline.transcription.utils.audio_utils.subprocess.run",
            side_effect=_ffmpeg_creates_chunks(tmp_path / "chunks", ["audio_000.mp3"]),
        ):
            split_audio_ffmpeg("/fake/audio.mp3", output_dir)

        assert txt_file.exists()
        assert txt_file.read_text() == "keep me"

    def test_chunk_duration_passed_to_ffmpeg_command(self, tmp_path):
        output_dir = str(tmp_path / "chunks")

        with patch(
            "iris.pipeline.transcription.utils.audio_utils.subprocess.run",
            side_effect=_ffmpeg_creates_chunks(tmp_path / "chunks", ["audio_000.mp3"]),
        ) as mock_run:
            split_audio_ffmpeg("/fake/audio.mp3", output_dir, chunk_duration=300)

        cmd = mock_run.call_args[0][0]
        seg_idx = cmd.index("-segment_time")
        assert cmd[seg_idx + 1] == "300"

    def test_ffmpeg_called_with_correct_encoding_params(self, tmp_path):
        output_dir = str(tmp_path / "chunks")

        with patch(
            "iris.pipeline.transcription.utils.audio_utils.subprocess.run",
            side_effect=_ffmpeg_creates_chunks(tmp_path / "chunks", ["audio_000.mp3"]),
        ) as mock_run:
            split_audio_ffmpeg("/fake/audio.mp3", output_dir)

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "-acodec" in cmd
        assert cmd[cmd.index("-acodec") + 1] == "libmp3lame"
        assert cmd[cmd.index("-ar") + 1] == "16000"
        assert cmd[cmd.index("-ac") + 1] == "1"
        assert cmd[cmd.index("-b:a") + 1] == "64k"
        # Security: shell=False
        assert mock_run.call_args[1]["shell"] is False
        assert mock_run.call_args[1]["check"] is True

    def test_output_template_uses_input_filename(self, tmp_path):
        output_dir = str(tmp_path / "chunks")

        with patch(
            "iris.pipeline.transcription.utils.audio_utils.subprocess.run",
            side_effect=_ffmpeg_creates_chunks(
                tmp_path / "chunks", ["my_lecture_000.mp3"]
            ),
        ) as mock_run:
            split_audio_ffmpeg("/data/my_lecture.mp3", output_dir)

        cmd = mock_run.call_args[0][0]
        # The output template should be based on input filename
        output_arg = cmd[-2]  # -y is last, template is second to last
        assert "my_lecture_" in output_arg
        assert output_arg.endswith(".mp3")

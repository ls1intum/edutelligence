"""Tests for audio splitting utilities."""

import os
import subprocess
from unittest.mock import patch

import pytest

from iris.pipeline.transcription.utils.audio_utils import split_audio_ffmpeg


class TestSplitAudioFfmpeg:
    def test_successful_split(self, tmp_path):
        output_dir = str(tmp_path / "chunks")
        os.makedirs(output_dir)
        # Pre-create fake chunk files to simulate FFmpeg output
        for i in range(3):
            (tmp_path / "chunks" / f"audio_{i:03d}.mp3").write_bytes(b"chunk")

        with patch("iris.pipeline.transcription.utils.audio_utils.subprocess.run"):
            result = split_audio_ffmpeg("/fake/audio.mp3", output_dir, chunk_duration=900)

        assert len(result) == 3
        assert all(path.endswith(".mp3") for path in result)
        # Verify sorted order
        assert result == sorted(result)

    def test_ffmpeg_failure_raises_runtime_error(self, tmp_path):
        output_dir = str(tmp_path / "chunks")

        with patch(
            "iris.pipeline.transcription.utils.audio_utils.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "ffmpeg", stderr="error msg"),
        ):
            with pytest.raises(RuntimeError, match="FFmpeg audio split failed"):
                split_audio_ffmpeg("/fake/audio.mp3", output_dir)

    def test_no_chunks_generated_raises_runtime_error(self, tmp_path):
        output_dir = str(tmp_path / "chunks")

        with patch("iris.pipeline.transcription.utils.audio_utils.subprocess.run"):
            with pytest.raises(RuntimeError, match="No chunks were generated"):
                split_audio_ffmpeg("/fake/audio.mp3", output_dir)

    def test_creates_output_dir_if_missing(self, tmp_path):
        output_dir = str(tmp_path / "new_dir" / "chunks")
        assert not os.path.exists(output_dir)

        with patch("iris.pipeline.transcription.utils.audio_utils.subprocess.run") as mock_run:
            # Pre-create chunk after makedirs runs (simulating FFmpeg)
            def side_effect(*args, **kwargs):
                (tmp_path / "new_dir" / "chunks" / "audio_000.mp3").write_bytes(b"chunk")

            mock_run.side_effect = side_effect

            result = split_audio_ffmpeg("/fake/audio.mp3", output_dir)

        assert os.path.exists(output_dir)
        assert len(result) == 1

    def test_cleans_old_chunks_before_splitting(self, tmp_path):
        output_dir = str(tmp_path / "chunks")
        os.makedirs(output_dir)
        # Create an old chunk
        old_chunk = tmp_path / "chunks" / "old_000.mp3"
        old_chunk.write_bytes(b"old data")

        with patch("iris.pipeline.transcription.utils.audio_utils.subprocess.run"):
            # After cleanup, create new chunks
            new_chunk = tmp_path / "chunks" / "new_000.mp3"
            new_chunk.write_bytes(b"new data")

            result = split_audio_ffmpeg("/fake/audio.mp3", output_dir)

        # Old chunk should be gone, only new chunk remains
        assert not old_chunk.exists()
        assert len(result) == 1

    def test_chunk_duration_passed_to_ffmpeg(self, tmp_path):
        output_dir = str(tmp_path / "chunks")
        os.makedirs(output_dir)
        (tmp_path / "chunks" / "a_000.mp3").write_bytes(b"chunk")

        with patch("iris.pipeline.transcription.utils.audio_utils.subprocess.run") as mock_run:
            split_audio_ffmpeg("/fake/audio.mp3", output_dir, chunk_duration=300)

        cmd = mock_run.call_args[0][0]
        # Verify segment_time argument
        seg_idx = cmd.index("-segment_time")
        assert cmd[seg_idx + 1] == "300"
        # Verify shell=False for security
        assert mock_run.call_args[1]["shell"] is False

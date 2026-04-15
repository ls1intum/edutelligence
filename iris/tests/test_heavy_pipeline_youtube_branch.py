from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from iris.domain.data.video_source_type import VideoSourceType
from iris.pipeline.shared.transcription.heavy_pipeline import (
    HeavyTranscriptionPipeline,
)
from iris.pipeline.shared.transcription.youtube_utils import (
    YouTubeDownloadError,
)

_MOD = "iris.pipeline.shared.transcription.heavy_pipeline"


@pytest.fixture
def mock_pipeline(tmp_path):
    """Fixture that does NOT pre-create the video file. The test passes only if
    the code under test actually invokes a download function that writes it.
    Stage-2 audio is fine to stub, but stage-1 video materialization is the
    behavior we're testing — don't fake it away."""
    callback = MagicMock()
    storage = MagicMock()
    storage.video_path = str(tmp_path / "video.mp4")
    storage.audio_path = str(tmp_path / "audio.m4a")
    # Stage 2 audio: stubbed separately; pre-create the audio file since we
    # don't exercise extract_audio's real behavior here.
    Path(storage.audio_path).write_bytes(b"\x00" * 1024)

    def _materialize_video(*args, **kwargs):
        # Both download_video (positional: url, path) and
        # download_youtube_video (positional: url, path) take path as the
        # second arg. Write the file only when the correct branch is invoked.
        target = (
            Path(args[1])
            if len(args) >= 2
            else Path(kwargs.get("output_path", storage.video_path))
        )
        target.write_bytes(b"\x00" * 1024)

    # Replace WhisperClient with a mock that returns a trivial transcript
    with patch(f"{_MOD}.WhisperClient") as wc_cls:
        wc = MagicMock()
        wc.transcribe.return_value = {"segments": [], "language": "en"}
        wc_cls.return_value = wc
        with patch(f"{_MOD}.extract_audio"):
            yield (
                HeavyTranscriptionPipeline(
                    callback=callback, storage=storage
                ),
                storage,
                callback,
                _materialize_video,
            )


def test_tum_live_branch_uses_ffmpeg_download(mock_pipeline):
    pipeline, _, _, materialize = mock_pipeline
    with ExitStack() as stack:
        dl_hls = stack.enter_context(
            patch(f"{_MOD}.download_video", side_effect=materialize)
        )
        dl_yt = stack.enter_context(
            patch(f"{_MOD}.download_youtube_video", side_effect=materialize)
        )
        v_yt = stack.enter_context(
            patch(f"{_MOD}.validate_youtube_video")
        )
        pipeline(
            "https://live.rbg.tum.de/foo.m3u8",
            lecture_unit_id=1,
            video_source_type=VideoSourceType.TUM_LIVE,
        )
    dl_hls.assert_called_once()
    dl_yt.assert_not_called()
    v_yt.assert_not_called()


def test_youtube_branch_validates_then_downloads_via_yt_dlp(mock_pipeline):
    pipeline, _, _, materialize = mock_pipeline
    with ExitStack() as stack:
        dl_hls = stack.enter_context(
            patch(f"{_MOD}.download_video", side_effect=materialize)
        )
        dl_yt = stack.enter_context(
            patch(f"{_MOD}.download_youtube_video", side_effect=materialize)
        )
        v_yt = stack.enter_context(
            patch(f"{_MOD}.validate_youtube_video")
        )
        v_yt.return_value = {"duration": 120, "title": "t"}
        pipeline(
            "https://youtu.be/dQw4w9WgXcQ",
            lecture_unit_id=1,
            video_source_type=VideoSourceType.YOUTUBE,
        )
    v_yt.assert_called_once()
    dl_yt.assert_called_once()
    dl_hls.assert_not_called()


def test_youtube_validation_failure_propagates(mock_pipeline):
    pipeline, _, _, _ = mock_pipeline
    with patch(
        f"{_MOD}.validate_youtube_video",
        side_effect=YouTubeDownloadError("YOUTUBE_PRIVATE", "private"),
    ):
        with pytest.raises(YouTubeDownloadError) as excinfo:
            pipeline(
                "https://youtu.be/X",
                lecture_unit_id=1,
                video_source_type=VideoSourceType.YOUTUBE,
            )
        assert excinfo.value.error_code == "YOUTUBE_PRIVATE"


def test_missing_source_type_defaults_to_tum_live(mock_pipeline):
    """Backward compat: callers omitting video_source_type get TUM_LIVE."""
    pipeline, _, _, materialize = mock_pipeline
    with ExitStack() as stack:
        dl_hls = stack.enter_context(
            patch(f"{_MOD}.download_video", side_effect=materialize)
        )
        dl_yt = stack.enter_context(
            patch(f"{_MOD}.download_youtube_video", side_effect=materialize)
        )
        pipeline("https://live.rbg.tum.de/foo.m3u8", lecture_unit_id=1)
    dl_hls.assert_called_once()
    dl_yt.assert_not_called()

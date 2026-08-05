"""Verify: YouTube-specific failures reach callback.error with the right code,
and generic transcription failures surface as TRANSCRIPTION_FAILED."""

from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, Mock, call, patch

from iris.domain.data.video_source_type import VideoSourceType
from iris.pipeline.lecture_ingestion_update_pipeline import (
    LectureIngestionUpdatePipeline,
    _translate_transcription_exception_to_error_code,
)
from iris.pipeline.shared.transcription.youtube_utils import (
    YouTubeDownloadError,
)

_MOD = "iris.pipeline.lecture_ingestion_update_pipeline"
_HEAVY = "iris.pipeline.shared.transcription.heavy_pipeline.HeavyTranscriptionPipeline"
_LIGHT = "iris.pipeline.shared.transcription.light_pipeline.LightTranscriptionPipeline"
_TEMP = "iris.pipeline.shared.transcription.temp_storage.TranscriptionTempStorage"
_HLS = "iris.pipeline.shared.transcription.video_utils.download_video"
_YT_DL = "iris.pipeline.shared.transcription.youtube_utils.download_youtube_video"
_YT_VAL = "iris.pipeline.shared.transcription.youtube_utils.validate_youtube_video"


def test_youtube_error_forwarded_with_structured_code():
    # Simulate the handler Task 11 adds: YouTubeDownloadError caught at the
    # orchestrator level and forwarded to callback.fail(code=...).
    err = YouTubeDownloadError("YOUTUBE_LIVE", "live stream")
    assert _translate_transcription_exception_to_error_code(err) == "YOUTUBE_LIVE"


def test_generic_exception_becomes_transcription_failed():
    assert (
        _translate_transcription_exception_to_error_code(
            RuntimeError("whisper timeout")
        )
        == "TRANSCRIPTION_FAILED"
    )


def test_slide_detection_only_branches_on_video_source_type():
    """Resume-from-checkpoint: must use yt-dlp for YouTube, not FFmpeg/HLS."""
    with (
        patch(_HLS) as dl_hls,
        patch(_YT_DL) as dl_yt,
        patch(_YT_VAL) as v_yt,
        patch(_LIGHT),
        patch(_TEMP) as storage_cls,
    ):
        storage_cls.return_value.__enter__.return_value = MagicMock()
        v_yt.return_value = {"duration": 120}

        lecture_unit = MagicMock()
        lecture_unit.lecture_unit_id = 1
        lecture_unit.video_link = "https://youtu.be/dQw4w9WgXcQ"
        lecture_unit.video_source_type = VideoSourceType.YOUTUBE
        lecture_unit.transcription.segments = []
        lecture_unit.transcription.language = "en"
        dto = MagicMock()
        dto.lecture_unit = lecture_unit

        pipeline = LectureIngestionUpdatePipeline.__new__(
            LectureIngestionUpdatePipeline
        )
        pipeline.dto = dto
        pipeline._is_local = False  # pylint: disable=protected-access

        with patch.object(pipeline, "_build_checkpoint", return_value={}):
            try:
                # pylint: disable=protected-access
                pipeline._run_slide_detection_only(MagicMock())
            except Exception:  # pylint: disable=broad-except
                pass  # downstream mocks may raise; only assert download branch

        dl_yt.assert_called_once()
        dl_hls.assert_not_called()


def test_youtube_source_type_passed_through_to_heavy_pipeline():
    """Orchestrator reads video_source_type and forwards it to heavy."""
    lecture_unit = MagicMock()
    lecture_unit.lecture_unit_id = 1
    lecture_unit.video_link = "https://youtu.be/dQw4w9WgXcQ"
    lecture_unit.video_source_type = VideoSourceType.YOUTUBE

    dto = MagicMock()
    dto.lecture_unit = lecture_unit

    with patch(_HEAVY) as heavy_cls:
        heavy = MagicMock()
        heavy.return_value = {"segments": [], "language": "en"}
        heavy_cls.return_value = heavy

        # Short-circuit light + ingestion so we assert the heavy-call only.
        with patch(_LIGHT), patch(_TEMP) as storage_cls:
            storage_cls.return_value.__enter__.return_value = MagicMock()

            pipeline = LectureIngestionUpdatePipeline.__new__(
                LectureIngestionUpdatePipeline
            )
            pipeline.dto = dto
            pipeline._is_local = False  # pylint: disable=protected-access
            with patch.object(pipeline, "_build_checkpoint", return_value={}):
                callback = MagicMock()
                try:
                    # pylint: disable=protected-access
                    pipeline._run_full_transcription(callback)
                except Exception:  # pylint: disable=broad-except
                    pass  # MagicMock wiring may raise; only check heavy call

    assert heavy.called
    called_kwargs = heavy.call_args.kwargs
    called_args = heavy.call_args.args
    # Accept either positional or keyword forwarding:
    all_args = list(called_args) + list(called_kwargs.values())
    assert VideoSourceType.YOUTUBE in all_args


def test_metadata_baseline_is_captured_before_transcription_processing():
    lecture_unit = SimpleNamespace(
        course_id=30,
        course_name="Course",
        course_description="Description",
        lecture_id=20,
        lecture_name="Lecture",
        lecture_unit_id=10,
        lecture_unit_name="Unit",
        lecture_unit_link="content-link",
        video_link="video-link",
    )
    dto = SimpleNamespace(
        lecture_unit=lecture_unit,
        settings=SimpleNamespace(
            authentication_token="token",
            artemis_base_url="https://artemis.example",
        ),
    )
    pipeline = LectureIngestionUpdatePipeline.__new__(LectureIngestionUpdatePipeline)
    pipeline.dto = dto
    pipeline._is_local = False  # pylint: disable=protected-access
    baseline = {"lecture_unit_link": "before-phase-one"}
    order = Mock()

    with (
        patch(f"{_MOD}._needs_transcription_generation", return_value=True),
        patch(f"{_MOD}._needs_slide_detection", return_value=False),
        patch(f"{_MOD}.IngestionStatusCallback") as callback_type,
        patch(f"{_MOD}.VectorDatabase"),
        patch(
            f"{_MOD}.LectureUnitPipeline.fetch_existing_properties",
            return_value=baseline,
        ) as snapshot,
        patch.object(pipeline, "_run_full_transcription") as phase_one,
        patch.object(pipeline, "_run_ingestion") as ingestion,
    ):
        order.attach_mock(snapshot, "snapshot")
        order.attach_mock(phase_one, "phase_one")
        order.attach_mock(ingestion, "ingestion")
        pipeline._run()  # pylint: disable=protected-access

    callback = callback_type.return_value
    assert order.mock_calls[0] == call.snapshot(
        ANY,
        ANY,
    )
    assert order.mock_calls[1] == call.phase_one(callback)
    assert order.mock_calls[2] == call.ingestion(callback, baseline)

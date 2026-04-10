"""Tests for LectureIngestionUpdatePipeline helpers and dispatch logic.

These cover main's unified transcription + ingestion flow: the gate
predicates that decide which phase to run, the pure checkpoint builder,
the DTO mutation helper, and the __call__ dispatch itself.
"""

# pylint: disable=protected-access,redefined-outer-name,unused-argument,missing-class-docstring

from unittest.mock import MagicMock, patch

import pytest

from iris.domain.data.lecture_unit_page_dto import LectureUnitPageDTO
from iris.domain.data.metrics.transcription_dto import (
    TranscriptionDTO,
    TranscriptionSegmentDTO,
)
from iris.domain.ingestion.ingestion_pipeline_execution_dto import (
    IngestionPipelineExecutionDto,
)
from iris.domain.pipeline_execution_settings_dto import (
    PipelineExecutionSettingsDTO,
)
from iris.pipeline import lecture_ingestion_update_pipeline as pipeline_module
from iris.pipeline.lecture_ingestion_update_pipeline import (
    LectureIngestionUpdatePipeline,
    _any_transcription_stage_needed,
    _needs_slide_detection,
    _needs_transcription_generation,
)


def _make_lecture_unit(
    *,
    video_link: str = "",
    transcription: TranscriptionDTO = None,
    pdf_file: str = "",
) -> LectureUnitPageDTO:
    # LectureUnitPageDTO.transcription has a None default but its annotation
    # is not Optional, so Pydantic v2 refuses an explicit transcription=None.
    # Omit the kwarg to let the default apply.
    kwargs = dict(
        lectureUnitId=42,
        lectureId=7,
        courseId=1,
        lectureName="Algo",
        lectureUnitName="Unit 1",
        pdfFile=pdf_file,
        videoLink=video_link,
    )
    if transcription is not None:
        kwargs["transcription"] = transcription
    return LectureUnitPageDTO(**kwargs)


def _make_dto(
    *,
    video_link: str = "",
    transcription: TranscriptionDTO = None,
    pdf_file: str = "",
) -> IngestionPipelineExecutionDto:
    settings = PipelineExecutionSettingsDTO(
        authenticationToken="tok-123",
        artemisBaseUrl="http://artemis.local",
    )
    return IngestionPipelineExecutionDto(
        pyrisLectureUnit=_make_lecture_unit(
            video_link=video_link,
            transcription=transcription,
            pdf_file=pdf_file,
        ),
        lectureUnitId=42,
        settings=settings,
        initialStages=[],
    )


@pytest.fixture
def enable_transcription(monkeypatch):
    """Flip the transcription feature flag on for a single test."""
    monkeypatch.setattr(
        pipeline_module.settings.transcription, "enabled", True, raising=True
    )
    monkeypatch.setattr(
        pipeline_module.settings.transcription,
        "temp_dir",
        "tmp/test-transcription",
        raising=True,
    )


class TestNeedsTranscriptionGeneration:
    def test_false_when_feature_disabled(self, monkeypatch):
        monkeypatch.setattr(
            pipeline_module.settings.transcription, "enabled", False, raising=True
        )
        dto = _make_dto(video_link="https://vid/foo.m3u8")
        assert _needs_transcription_generation(dto) is False

    def test_false_when_video_link_empty(self, enable_transcription):
        dto = _make_dto(video_link="")
        assert _needs_transcription_generation(dto) is False

    def test_false_when_transcription_already_present(self, enable_transcription):
        existing = TranscriptionDTO(
            language="en",
            segments=[
                TranscriptionSegmentDTO(
                    startTime=0.0, endTime=1.0, text="x", slideNumber=0
                )
            ],
        )
        dto = _make_dto(video_link="https://vid/foo.m3u8", transcription=existing)
        assert _needs_transcription_generation(dto) is False

    def test_true_when_enabled_and_no_transcription(self, enable_transcription):
        dto = _make_dto(video_link="https://vid/foo.m3u8")
        assert _needs_transcription_generation(dto) is True

    def test_true_when_transcription_segments_is_none(self, enable_transcription):
        empty = TranscriptionDTO(language="en", segments=None)
        dto = _make_dto(video_link="https://vid/foo.m3u8", transcription=empty)
        assert _needs_transcription_generation(dto) is True


class TestNeedsSlideDetection:
    def test_false_when_feature_disabled(self, monkeypatch):
        monkeypatch.setattr(
            pipeline_module.settings.transcription, "enabled", False, raising=True
        )
        dto = _make_dto(video_link="https://vid/foo.m3u8")
        assert _needs_slide_detection(dto) is False

    def test_false_when_video_link_empty(self, enable_transcription):
        dto = _make_dto(video_link="")
        assert _needs_slide_detection(dto) is False

    def test_false_when_transcription_none(self, enable_transcription):
        dto = _make_dto(video_link="https://vid/foo.m3u8")
        assert _needs_slide_detection(dto) is False

    def test_false_when_any_segment_has_slide_number(self, enable_transcription):
        # An enriched transcript: at least one segment has a real slide number
        transcription = TranscriptionDTO(
            language="en",
            segments=[
                TranscriptionSegmentDTO(
                    startTime=0.0, endTime=1.0, text="a", slideNumber=0
                ),
                TranscriptionSegmentDTO(
                    startTime=1.0, endTime=2.0, text="b", slideNumber=3
                ),
            ],
        )
        dto = _make_dto(video_link="https://vid/foo.m3u8", transcription=transcription)
        assert _needs_slide_detection(dto) is False

    def test_true_when_all_segments_have_default_slide_number(
        self, enable_transcription
    ):
        # A raw transcript from a checkpoint: every segment has slide_number == 0
        transcription = TranscriptionDTO(
            language="en",
            segments=[
                TranscriptionSegmentDTO(
                    startTime=0.0, endTime=1.0, text="a", slideNumber=0
                ),
                TranscriptionSegmentDTO(
                    startTime=1.0, endTime=2.0, text="b", slideNumber=0
                ),
            ],
        )
        dto = _make_dto(video_link="https://vid/foo.m3u8", transcription=transcription)
        assert _needs_slide_detection(dto) is True


class TestAnyTranscriptionStageNeeded:
    def test_false_when_neither_needed(self, monkeypatch):
        monkeypatch.setattr(
            pipeline_module.settings.transcription, "enabled", False, raising=True
        )
        dto = _make_dto(video_link="https://vid/foo.m3u8")
        assert _any_transcription_stage_needed(dto) is False

    def test_true_when_generation_needed(self, enable_transcription):
        dto = _make_dto(video_link="https://vid/foo.m3u8")
        assert _any_transcription_stage_needed(dto) is True

    def test_true_when_only_slide_detection_needed(self, enable_transcription):
        transcription = TranscriptionDTO(
            language="en",
            segments=[
                TranscriptionSegmentDTO(
                    startTime=0.0, endTime=1.0, text="a", slideNumber=0
                ),
            ],
        )
        dto = _make_dto(video_link="https://vid/foo.m3u8", transcription=transcription)
        assert _any_transcription_stage_needed(dto) is True


class TestBuildCheckpoint:
    def test_non_enriched_produces_camelcase_segments(self):
        raw = {
            "segments": [
                {"start": 0.0, "end": 5.0, "text": "  hello  "},
                {"start": 5.0, "end": 10.0, "text": "world"},
            ],
            "language": "de",
        }
        cp = LectureIngestionUpdatePipeline._build_checkpoint(
            raw, lecture_unit_id=42, enriched=False
        )
        assert cp["lectureUnitId"] == 42
        assert cp["language"] == "de"
        assert cp["segments"] == [
            {"startTime": 0.0, "endTime": 5.0, "text": "hello", "slideNumber": 0},
            {"startTime": 5.0, "endTime": 10.0, "text": "world", "slideNumber": 0},
        ]

    def test_default_language_when_missing(self):
        raw = {"segments": []}
        cp = LectureIngestionUpdatePipeline._build_checkpoint(
            raw, lecture_unit_id=42, enriched=False
        )
        assert cp["language"] == "en"
        assert cp["segments"] == []

    def test_enriched_uses_aligned_segments_verbatim(self):
        raw = {"segments": [{"start": 0.0, "end": 1.0, "text": "ignored"}]}
        aligned = [
            {"startTime": 0.0, "endTime": 1.0, "text": "keep", "slideNumber": 2},
        ]
        cp = LectureIngestionUpdatePipeline._build_checkpoint(
            raw,
            lecture_unit_id=99,
            enriched=True,
            aligned_segments=aligned,
        )
        assert cp["lectureUnitId"] == 99
        assert cp["segments"] is aligned

    def test_enriched_without_aligned_falls_back_to_raw(self):
        # Defensive path: if enriched=True but aligned_segments is None we
        # still produce a valid checkpoint from the raw transcript.
        raw = {
            "segments": [{"start": 0.0, "end": 1.0, "text": "x"}],
            "language": "en",
        }
        cp = LectureIngestionUpdatePipeline._build_checkpoint(
            raw, lecture_unit_id=1, enriched=True, aligned_segments=None
        )
        assert cp["segments"] == [
            {"startTime": 0.0, "endTime": 1.0, "text": "x", "slideNumber": 0}
        ]


class TestUpdateDtoWithTranscript:
    def test_mutates_dto_transcription_field(self):
        dto = _make_dto(video_link="https://vid/foo.m3u8")
        pipeline = LectureIngestionUpdatePipeline(dto)
        aligned = [
            {"startTime": 0.0, "endTime": 1.0, "text": "a", "slideNumber": 1},
            {"startTime": 1.0, "endTime": 2.0, "text": "b", "slideNumber": 2},
        ]
        pipeline._update_dto_with_transcript(aligned, language="de")
        transcription = dto.lecture_unit.transcription
        assert transcription.language == "de"
        assert len(transcription.segments) == 2
        assert transcription.segments[0].start_time == 0.0
        assert transcription.segments[0].end_time == 1.0
        assert transcription.segments[0].text == "a"
        assert transcription.segments[0].slide_number == 1
        assert transcription.segments[1].slide_number == 2


class TestDispatch:
    """Verify __call__ routes to the correct phase method."""

    def _build_pipeline(self, dto):
        pipeline = LectureIngestionUpdatePipeline(dto)
        pipeline._run_full_transcription = MagicMock()
        pipeline._run_slide_detection_only = MagicMock()
        pipeline._run_ingestion = MagicMock()
        return pipeline

    @patch.object(pipeline_module, "IngestionStatusCallback")
    def test_dispatches_to_full_transcription_when_generation_needed(
        self, mock_callback_cls, enable_transcription
    ):
        dto = _make_dto(video_link="https://vid/foo.m3u8")
        pipeline = self._build_pipeline(dto)
        pipeline()
        pipeline._run_full_transcription.assert_called_once()
        pipeline._run_slide_detection_only.assert_not_called()
        pipeline._run_ingestion.assert_called_once()
        # Transcription stages should be requested on the callback
        assert (
            mock_callback_cls.call_args.kwargs["include_transcription_stages"] is True
        )

    @patch.object(pipeline_module, "IngestionStatusCallback")
    def test_dispatches_to_slide_detection_only_when_only_slides_needed(
        self, mock_callback_cls, enable_transcription
    ):
        raw_only = TranscriptionDTO(
            language="en",
            segments=[
                TranscriptionSegmentDTO(
                    startTime=0.0, endTime=1.0, text="x", slideNumber=0
                ),
            ],
        )
        dto = _make_dto(video_link="https://vid/foo.m3u8", transcription=raw_only)
        pipeline = self._build_pipeline(dto)
        pipeline()
        pipeline._run_full_transcription.assert_not_called()
        pipeline._run_slide_detection_only.assert_called_once()
        pipeline._run_ingestion.assert_called_once()
        assert (
            mock_callback_cls.call_args.kwargs["include_transcription_stages"] is True
        )

    @patch.object(pipeline_module, "IngestionStatusCallback")
    def test_skips_transcription_when_feature_disabled(
        self, mock_callback_cls, monkeypatch
    ):
        monkeypatch.setattr(
            pipeline_module.settings.transcription, "enabled", False, raising=True
        )
        dto = _make_dto(video_link="https://vid/foo.m3u8")
        pipeline = self._build_pipeline(dto)
        pipeline()
        pipeline._run_full_transcription.assert_not_called()
        pipeline._run_slide_detection_only.assert_not_called()
        pipeline._run_ingestion.assert_called_once()
        assert (
            mock_callback_cls.call_args.kwargs["include_transcription_stages"] is False
        )

    @patch.object(pipeline_module, "IngestionStatusCallback")
    def test_reports_error_to_callback_on_exception(
        self, mock_callback_cls, monkeypatch
    ):
        monkeypatch.setattr(
            pipeline_module.settings.transcription, "enabled", False, raising=True
        )
        dto = _make_dto(video_link="")
        pipeline = self._build_pipeline(dto)
        pipeline._run_ingestion.side_effect = RuntimeError("boom")
        pipeline()
        callback = mock_callback_cls.return_value
        callback.error.assert_called_once()
        # first positional arg is the error message, kwargs carry the exception
        args, kwargs = callback.error.call_args
        assert "boom" in args[0]
        assert isinstance(kwargs["exception"], RuntimeError)

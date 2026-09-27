"""Stage names and progress reported to Artemis while a video unit is transcribed."""

# pylint: disable=protected-access

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from iris.pipeline.lecture_ingestion_update_pipeline import (
    LectureIngestionUpdatePipeline,
)
from iris.pipeline.shared.transcription.heavy_pipeline import HeavyTranscriptionPipeline
from iris.pipeline.shared.transcription.light_pipeline import LightTranscriptionPipeline
from iris.pipeline.shared.transcription.slide_turn_detector import SlideTurnDetector
from iris.pipeline.transcription_ingestion_pipeline import (
    TranscriptionIngestionPipeline,
)

STAGE_FIELDS = ("stage_name", "stage_progress", "stage_total")


def _stage_updates(callback):
    """The stage fields of every update call that set a stage name."""
    return [
        tuple(call.kwargs.get(field) for field in STAGE_FIELDS)
        for call in callback.update.call_args_list
        if "stage_name" in call.kwargs
    ]


def test_heavy_pipeline_reports_each_step_and_whisper_chunks(tmp_path):
    pipeline = HeavyTranscriptionPipeline.__new__(HeavyTranscriptionPipeline)
    pipeline.callback = MagicMock()
    pipeline.cancel_event = None
    pipeline.storage = SimpleNamespace(
        video_path=str(tmp_path / "video.mp4"),
        audio_path=str(tmp_path / "audio.m4a"),
    )
    tmp_path.joinpath("video.mp4").write_bytes(b"video")
    tmp_path.joinpath("audio.m4a").write_bytes(b"audio")

    def whisper_transcribe(*_args, **kwargs):
        kwargs["on_chunk_complete"](1, 2)
        kwargs["on_chunk_complete"](2, 2)
        return {"segments": [], "language": "en"}

    pipeline.whisper_client = SimpleNamespace(
        transcribe=MagicMock(side_effect=whisper_transcribe)
    )

    with (
        patch("iris.pipeline.shared.transcription.heavy_pipeline.download_video"),
        patch("iris.pipeline.shared.transcription.heavy_pipeline.extract_audio"),
    ):
        HeavyTranscriptionPipeline.__call__.__wrapped__(
            pipeline, "https://live.rbg.tum.de/foo.m3u8", lecture_unit_id=3
        )

    assert _stage_updates(pipeline.callback) == [
        ("downloading", None, None),
        ("extracting-audio", None, None),
        ("transcribing", 0, None),
        ("transcribing", 1, 2),
        ("transcribing", 2, 2),
    ]


def test_slide_detection_progress_counts_failed_vision_calls(tmp_path):
    reported = []
    segments = [{"start": float(i), "end": float(i + 1)} for i in range(4)]
    detector = SlideTurnDetector(
        video_path=str(tmp_path / "missing.mp4"),
        segments=segments,
        request_handler=MagicMock(),
        on_progress=lambda checked, total: reported.append((checked, total)),
    )
    detector.frame_cache = MagicMock()
    detector.frame_cache.get.return_value = "frame"

    # A failed vision call yields no label but must still move the counter
    with patch.object(detector, "_ask_gpt_for_slide_number", return_value=None):
        detector.labels[0] = detector._query_label(0)
        detector.labels[3] = detector._query_label(3)

    assert detector.labels == [None, None, None, None]
    assert reported == [(1, 4), (2, 4)]


def test_light_pipeline_forwards_the_checked_counter():
    pipeline = LightTranscriptionPipeline.__new__(LightTranscriptionPipeline)
    pipeline.callback = MagicMock()
    pipeline.cancel_event = None
    pipeline.video_path = "/tmp/video.mp4"
    pipeline.request_handler = MagicMock()
    segments = [{"start": float(i), "end": float(i + 1), "text": "a"} for i in range(4)]

    def detect(*_args, **kwargs):
        kwargs["on_progress"](2, 4)
        return []

    with (
        patch(
            "iris.pipeline.shared.transcription.light_pipeline.detect_slide_timestamps",
            side_effect=detect,
        ),
        patch(
            "iris.pipeline.shared.transcription.light_pipeline.align_slides_with_segments",
            return_value=[],
        ),
    ):
        LightTranscriptionPipeline.__call__.__wrapped__(
            pipeline, {"segments": segments}, lecture_unit_id=3
        )

    assert _stage_updates(pipeline.callback) == [
        ("aligning-slides", 0, 4),
        ("aligning-slides", 2, 4),
    ]


def test_enriched_checkpoint_clears_the_transcription_stage():
    pipeline = LectureIngestionUpdatePipeline.__new__(LectureIngestionUpdatePipeline)
    pipeline.dto = SimpleNamespace(
        lecture_unit=SimpleNamespace(
            lecture_unit_id=3, video_link="https://video", video_source_type=None
        )
    )
    pipeline.cancel_event = None
    pipeline._is_local = False
    pipeline._build_checkpoint = MagicMock(return_value={"segments": []})
    pipeline._update_dto_with_transcript = MagicMock()
    callback = MagicMock()
    storage = SimpleNamespace(video_path="/tmp/video.mp4")

    with (
        patch(
            "iris.pipeline.shared.transcription.heavy_pipeline.HeavyTranscriptionPipeline",
            return_value=MagicMock(return_value={"segments": [], "language": "en"}),
        ),
        patch(
            "iris.pipeline.shared.transcription.light_pipeline.LightTranscriptionPipeline",
            return_value=MagicMock(return_value=[]),
        ),
        patch(
            "iris.pipeline.shared.transcription.temp_storage.TranscriptionTempStorage",
            return_value=nullcontext(storage),
        ),
    ):
        pipeline._run_full_transcription(callback)

    enriched_checkpoint = callback.update.call_args_list[-1].kwargs
    assert "result" in enriched_checkpoint
    assert tuple(enriched_checkpoint[field] for field in STAGE_FIELDS) == (
        None,
        None,
        None,
    )


def test_transcript_chunking_reports_progress_around_semantic_splits():
    pipeline = TranscriptionIngestionPipeline.__new__(TranscriptionIngestionPipeline)
    pipeline.callback = MagicMock()
    pipeline.cancel_event = None
    pipeline.dto = SimpleNamespace(
        settings=SimpleNamespace(artemis_base_url="https://artemis.example")
    )
    pipeline.llm_embedding = MagicMock()
    pipeline.llm_embedding.split_text_semantically.side_effect = lambda text, **_: [
        text
    ]
    short_text = "short slide"
    long_text = "x" * 1300
    transcription = SimpleNamespace(
        course_id=1,
        lecture_id=2,
        lecture_unit_id=3,
        lecture_name="Lecture",
        lecture_unit_name="Unit",
        content_fingerprint="v1:fp",
        ingestion_run_id="run",
        transcription=SimpleNamespace(
            language="en",
            segments=[
                SimpleNamespace(
                    start_time=0.0, end_time=1.0, text=short_text, slide_number=1
                ),
                SimpleNamespace(
                    start_time=1.0, end_time=2.0, text=long_text, slide_number=2
                ),
            ],
        ),
    )

    pipeline.chunk_transcription(transcription)

    # Only the long group is split semantically; short groups pass through without an update
    assert _stage_updates(pipeline.callback) == [
        ("transcript-chunking", 0, 2),
        ("transcript-chunking", 1, 2),
        ("transcript-chunking", 2, 2),
    ]

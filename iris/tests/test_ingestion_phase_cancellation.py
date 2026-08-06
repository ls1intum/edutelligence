"""Focused cancellation checkpoints for superseded ingestion runs."""

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from iris.common.cancellation import sleep_unless_cancelled
from iris.common.custom_exceptions import IngestionCancelledException
from iris.ingestion.ingestion_job_registry import ingestion_job_commit_lock
from iris.pipeline.lecture_ingestion_pipeline import (
    LectureUnitPageIngestionPipeline,
)
from iris.pipeline.lecture_unit_pipeline import (
    LectureUnitPipeline,
)
from iris.pipeline.shared.transcription.heavy_pipeline import HeavyTranscriptionPipeline
from iris.pipeline.shared.transcription.light_pipeline import LightTranscriptionPipeline
from iris.pipeline.shared.transcription.slide_turn_detector import SlideTurnDetector
from iris.pipeline.shared.transcription.whisper_client import WhisperClient
from iris.pipeline.transcription_ingestion_pipeline import (
    TranscriptionIngestionPipeline,
)
from iris.vector_database.lecture_transcription_schema import (
    LectureTranscriptionSchema,
)
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
)


def _cancelled():
    event = threading.Event()
    event.set()
    return event


class _CancelledAfter(threading.Event):
    """Event that reports itself as set only from the nth check onwards.

    Lets a test reach a cancellation checkpoint that an earlier checkpoint on
    the same code path would otherwise shadow.
    """

    def __init__(self, checks_before_cancellation: int):
        super().__init__()
        self.remaining_checks = checks_before_cancellation

    def is_set(self) -> bool:
        if self.remaining_checks > 0:
            self.remaining_checks -= 1
            return False
        return True


def _cancel_then_vector(cancel_event):
    cancel_event.set()
    return [0.1]


def _whisper_client():
    """Whisper client wired for OpenAI without touching the LLM config."""
    client = WhisperClient.__new__(WhisperClient)
    client.llm = SimpleNamespace(api_key="key", model="whisper-1")
    client.chunk_duration = 900
    client.max_retries = 3
    client.max_workers = 2
    client.request_timeout = 1
    client.no_speech_threshold = 0.8
    client.provider_name = "OpenAI"
    return client


def _whisper_response(status_code):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = {"segments": [], "language": "english"}
    return response


def _signal_then_vector(reached):
    """Embedding stub that reports the run arrived at the commit phase."""

    def embed(*_args, **_kwargs):
        reached.set()
        return [0.1]

    return embed


def test_page_chunking_stops_after_first_page_vision_result():
    pipeline = LectureUnitPageIngestionPipeline.__new__(
        LectureUnitPageIngestionPipeline
    )
    pipeline.cancel_event = threading.Event()
    pipeline.callback = MagicMock()
    pipeline.get_course_language = MagicMock(return_value="en")

    def interpret_and_cancel(*_args, **_kwargs):
        pipeline.cancel_event.set()
        return SimpleNamespace(display_page_number=1, academic_description=None)

    pipeline.interpret_image = MagicMock(side_effect=interpret_and_cancel)

    pixmap = MagicMock()
    pixmap.tobytes.return_value = b"jpg"
    page = MagicMock()
    page.get_text.return_value = "text"
    page.get_pixmap.return_value = pixmap

    doc = MagicMock()
    doc.page_count = 2
    doc.load_page.return_value = page

    with patch("iris.pipeline.lecture_ingestion_pipeline.fitz.open", return_value=doc):
        with pytest.raises(IngestionCancelledException):
            pipeline.chunk_data(
                lecture_pdf="/tmp/x.pdf",
                lecture_unit_slide_dto=SimpleNamespace(
                    lecture_unit_id=3, lecture_name="L", lecture_unit_name="U"
                ),
                base_url="https://artemis.example",
            )

    assert pipeline.interpret_image.call_count == 1


def test_page_replacement_is_skipped_after_cancellation_during_embedding():
    pipeline = LectureUnitPageIngestionPipeline.__new__(
        LectureUnitPageIngestionPipeline
    )
    pipeline.cancel_event = threading.Event()
    pipeline.callback = MagicMock()
    pipeline.tokens = []
    pipeline.dto = SimpleNamespace(
        lecture_unit=SimpleNamespace(
            lecture_unit_id=3,
            course_id=1,
            lecture_id=2,
            lecture_unit_name="Unit",
            course_name="Course",
            pdf_file_base64="pdf",
        ),
        settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
    )
    pipeline.check_if_attachment_needs_update = MagicMock(return_value=True)
    pipeline.chunk_data = MagicMock(
        return_value=[
            {
                LectureUnitPageChunkSchema.PAGE_NUMBER.value: 1,
                LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value: "page",
            }
        ]
    )
    pipeline.llm_embedding = MagicMock()
    pipeline.llm_embedding.embed.side_effect = lambda _text: _cancel_then_vector(
        pipeline.cancel_event
    )
    pipeline.delete_lecture_unit = MagicMock()
    pipeline.collection = MagicMock()
    pipeline.collection.query.fetch_objects.return_value.objects = []
    pipeline.collection.batch.rate_limit.return_value.__enter__.return_value = (
        MagicMock()
    )
    pipeline.lecture_unit_collection = MagicMock()
    pipeline.lecture_unit_collection.query.fetch_objects.return_value.objects = []
    pipeline.get_course_language = MagicMock(return_value="en")

    with (
        patch(
            "iris.pipeline.lecture_ingestion_pipeline.save_pdf",
            return_value="/tmp/x.pdf",
        ),
        patch("iris.pipeline.lecture_ingestion_pipeline.cleanup_temporary_file"),
    ):
        with pytest.raises(IngestionCancelledException):
            LectureUnitPageIngestionPipeline.__call__.__wrapped__(pipeline)

    pipeline.delete_lecture_unit.assert_not_called()


def test_transcription_replacement_is_skipped_after_cancellation_during_embedding():
    pipeline = TranscriptionIngestionPipeline.__new__(TranscriptionIngestionPipeline)
    pipeline.cancel_event = threading.Event()
    pipeline.callback = MagicMock()
    pipeline.tokens = []
    pipeline.dto = SimpleNamespace(
        lecture_unit=SimpleNamespace(
            course_id=1,
            lecture_id=2,
            lecture_unit_id=3,
            lecture_name="Lecture",
            lecture_unit_name="Unit",
            transcription=SimpleNamespace(language="en"),
        ),
        settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
    )
    pipeline.chunk_transcription = MagicMock(
        return_value=[
            {LectureTranscriptionSchema.SEGMENT_TEXT.value: "segment", "page_number": 1}
        ]
    )
    pipeline.summarize_chunks = MagicMock(
        return_value=[
            {LectureTranscriptionSchema.SEGMENT_TEXT.value: "segment", "page_number": 1}
        ]
    )
    pipeline.llm_embedding = MagicMock()
    pipeline.llm_embedding.embed.side_effect = lambda _text: _cancel_then_vector(
        pipeline.cancel_event
    )
    pipeline.delete_existing_transcription_data = MagicMock()
    pipeline.collection = SimpleNamespace(
        batch=SimpleNamespace(dynamic=MagicMock(return_value=MagicMock()))
    )

    with pytest.raises(IngestionCancelledException):
        TranscriptionIngestionPipeline.__call__.__wrapped__(pipeline)

    pipeline.delete_existing_transcription_data.assert_not_called()


def test_heavy_transcription_stops_during_whisper_progress(tmp_path):
    pipeline = HeavyTranscriptionPipeline.__new__(HeavyTranscriptionPipeline)
    pipeline.callback = MagicMock()
    pipeline.cancel_event = threading.Event()
    pipeline.storage = SimpleNamespace(
        video_path=str(tmp_path / "video.mp4"),
        audio_path=str(tmp_path / "audio.m4a"),
    )
    tmp_path.joinpath("video.mp4").write_bytes(b"video")
    tmp_path.joinpath("audio.m4a").write_bytes(b"audio")

    def whisper_transcribe(*_args, **kwargs):
        pipeline.cancel_event.set()
        kwargs["on_chunk_complete"](1, 2)
        return {"segments": [], "language": "en"}

    pipeline.whisper_client = SimpleNamespace(
        transcribe=MagicMock(side_effect=whisper_transcribe)
    )

    with (
        patch("iris.pipeline.shared.transcription.heavy_pipeline.download_video"),
        patch("iris.pipeline.shared.transcription.heavy_pipeline.extract_audio"),
    ):
        with pytest.raises(IngestionCancelledException):
            HeavyTranscriptionPipeline.__call__.__wrapped__(
                pipeline,
                "https://live.rbg.tum.de/foo.m3u8",
                lecture_unit_id=3,
            )


def test_light_transcription_stops_during_slide_detection_progress():
    pipeline = LightTranscriptionPipeline.__new__(LightTranscriptionPipeline)
    pipeline.callback = MagicMock()
    pipeline.cancel_event = threading.Event()
    pipeline.video_path = "/tmp/video.mp4"
    pipeline.request_handler = MagicMock()

    def detect_side_effect(*_args, **kwargs):
        pipeline.cancel_event.set()
        kwargs["on_progress"](1, 4)
        return []

    with patch(
        "iris.pipeline.shared.transcription.light_pipeline.detect_slide_timestamps",
        side_effect=detect_side_effect,
    ):
        with pytest.raises(IngestionCancelledException):
            LightTranscriptionPipeline.__call__.__wrapped__(
                pipeline,
                {"segments": [{"start": 0.0, "end": 1.0, "text": "a"}]},
                lecture_unit_id=3,
            )


def test_light_transcription_cancellation_precedes_no_video_shortcut():
    pipeline = LightTranscriptionPipeline.__new__(LightTranscriptionPipeline)
    pipeline.callback = MagicMock()
    pipeline.cancel_event = _cancelled()
    pipeline.video_path = None

    with pytest.raises(IngestionCancelledException) as cancelled:
        LightTranscriptionPipeline.__call__.__wrapped__(
            pipeline,
            {"segments": [{"start": 0.0, "end": 1.0, "text": "a"}]},
            lecture_unit_id=3,
        )

    assert "before slide detection" in cancelled.value.reason
    pipeline.callback.update.assert_not_called()


def test_whisper_retry_wait_stops_when_cancelled():
    with pytest.raises(IngestionCancelledException):
        sleep_unless_cancelled(
            30, _cancelled(), lecture_unit_id=3, stage="whisper retry backoff"
        )


def test_whisper_retry_wait_stops_when_worker_cancelled(tmp_path):
    """A worker in retry backoff must abort once the run gives up.

    The failing chunk backs off for 10s. Shutting the run down waits for that
    worker, so the run only returns quickly if the backoff itself is
    interruptible.
    """
    chunks = []
    for index in range(2):
        chunk = tmp_path / f"chunk_{index}.mp3"
        chunk.write_bytes(b"audio")
        chunks.append(str(chunk))

    client = _whisper_client()
    backing_off = threading.Event()

    def post(*_args, **kwargs):
        chunk_name = kwargs["files"]["file"][0]
        if chunk_name.startswith("chunk_0"):
            return _whisper_response(200)
        backing_off.set()
        return _whisper_response(429)

    shutdown_started = None

    def fail_run(*_args, **_kwargs):
        nonlocal shutdown_started
        # Fails the run only once the other chunk sits in its retry backoff.
        assert backing_off.wait(timeout=5)
        shutdown_started = time.monotonic()
        raise RuntimeError("chunk bookkeeping failed")

    with (
        patch(
            "iris.pipeline.shared.transcription.whisper_client.split_audio_ffmpeg",
            return_value=chunks,
        ),
        patch(
            "iris.pipeline.shared.transcription.whisper_client._audio_duration",
            return_value=1.0,
        ),
        patch(
            "iris.pipeline.shared.transcription.whisper_client.requests.post",
            side_effect=post,
        ),
    ):
        with pytest.raises(RuntimeError):
            client.transcribe(
                "/tmp/audio.mp3",
                lecture_unit_id=3,
                on_chunk_complete=fail_run,
            )

    assert shutdown_started is not None
    assert (
        time.monotonic() - shutdown_started < 5
    ), "run waited out the full retry backoff"


def test_whisper_transcribe_stops_polling_when_cancelled():
    client = WhisperClient.__new__(WhisperClient)
    client.max_workers = 1
    client.max_retries = 1
    client.chunk_duration = 900
    client.no_speech_threshold = 0.8
    client.provider_name = "OpenAI"

    started = threading.Event()
    unblock = threading.Event()
    cancel_event = threading.Event()

    def blocking_chunk(*_args, **_kwargs):
        started.set()
        unblock.wait(timeout=5)
        return [], None

    def trigger_cancel():
        assert started.wait(timeout=5)
        cancel_event.set()

    canceller = threading.Thread(target=trigger_cancel)
    canceller.start()

    with (
        patch(
            "iris.pipeline.shared.transcription.whisper_client.split_audio_ffmpeg",
            return_value=["/tmp/chunk.mp3"],
        ),
        patch(
            "iris.pipeline.shared.transcription.whisper_client._audio_duration",
            return_value=1.0,
        ),
        patch.object(client, "_transcribe_chunk", side_effect=blocking_chunk),
    ):
        with pytest.raises(IngestionCancelledException):
            client.transcribe(
                "/tmp/audio.mp3", lecture_unit_id=3, cancel_event=cancel_event
            )

    unblock.set()
    canceller.join(timeout=5)


def test_slide_turn_detector_stops_before_vision_query():
    detector = SlideTurnDetector.__new__(SlideTurnDetector)
    # Cancellation arrives after detect() and its anchor loop already checked,
    # so only the checkpoint inside the label query can still stop the run.
    detector.cancel_event = _CancelledAfter(2)
    detector.segments = [{"start": 0.0}, {"start": 1.0}]
    detector.labels = [None, None]
    detector.anchor_stride = 1
    detector.min_stride = 1
    detector.job_id = "3"
    detector.on_progress = None
    detector.gpt_calls = 0
    detector.frame_cache = MagicMock()

    with pytest.raises(IngestionCancelledException) as cancelled:
        detector.detect()

    assert "slide vision query" in cancelled.value.reason
    detector.frame_cache.get.assert_not_called()


def _page_commit_target():
    """Page ingestion run stubbed down to the embedding and commit phases."""
    pipeline = LectureUnitPageIngestionPipeline.__new__(
        LectureUnitPageIngestionPipeline
    )
    pipeline.cancel_event = threading.Event()
    pipeline.callback = MagicMock()
    pipeline.tokens = []
    pipeline.course_language = "en"
    pipeline.dto = SimpleNamespace(
        lecture_unit=SimpleNamespace(
            lecture_unit_id=3,
            course_id=1,
            lecture_id=2,
            lecture_unit_name="Unit",
            course_name="Course",
            pdf_file_base64="pdf",
        ),
        settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
    )
    pipeline.check_if_attachment_needs_update = MagicMock(return_value=True)
    pipeline.chunk_data = MagicMock(
        return_value=[
            {
                LectureUnitPageChunkSchema.PAGE_NUMBER.value: 1,
                LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value: "page",
            }
        ]
    )
    pipeline.delete_lecture_unit = MagicMock()
    pipeline.collection = MagicMock()
    pipeline.collection.query.fetch_objects.return_value.objects = []
    pipeline.lecture_unit_collection = MagicMock()
    pipeline.lecture_unit_collection.query.fetch_objects.return_value.objects = []

    reached_commit = threading.Event()
    pipeline.llm_embedding = MagicMock()
    pipeline.llm_embedding.embed.side_effect = _signal_then_vector(reached_commit)

    def run():
        with (
            patch(
                "iris.pipeline.lecture_ingestion_pipeline.save_pdf",
                return_value="/tmp/x.pdf",
            ),
            patch("iris.pipeline.lecture_ingestion_pipeline.cleanup_temporary_file"),
        ):
            LectureUnitPageIngestionPipeline.__call__.__wrapped__(pipeline)

    return SimpleNamespace(
        run=run,
        commit_lock=lambda: ingestion_job_commit_lock(
            "https://artemis.example", 1, 2, 3
        ),
        cancel_event=pipeline.cancel_event,
        reached_commit=reached_commit,
        delete_mock=pipeline.delete_lecture_unit,
        insert_mock=pipeline.collection.batch.rate_limit,
    )


def _transcription_commit_target():
    """Transcription ingestion run stubbed down to embedding and commit."""
    pipeline = TranscriptionIngestionPipeline.__new__(TranscriptionIngestionPipeline)
    pipeline.cancel_event = threading.Event()
    pipeline.callback = MagicMock()
    pipeline.tokens = []
    pipeline.dto = SimpleNamespace(
        lecture_unit=SimpleNamespace(
            course_id=1,
            lecture_id=2,
            lecture_unit_id=3,
            lecture_name="Lecture",
            lecture_unit_name="Unit",
            transcription=SimpleNamespace(language="en"),
        ),
        settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
    )
    chunks = [
        {LectureTranscriptionSchema.SEGMENT_TEXT.value: "segment", "page_number": 1}
    ]
    pipeline.chunk_transcription = MagicMock(return_value=chunks)
    pipeline.summarize_chunks = MagicMock(return_value=chunks)
    pipeline.delete_existing_transcription_data = MagicMock()
    pipeline.collection = MagicMock()

    reached_commit = threading.Event()
    pipeline.llm_embedding = MagicMock()
    pipeline.llm_embedding.embed.side_effect = _signal_then_vector(reached_commit)

    def run():
        TranscriptionIngestionPipeline.__call__.__wrapped__(pipeline)

    return SimpleNamespace(
        run=run,
        commit_lock=lambda: ingestion_job_commit_lock(
            "https://artemis.example", 1, 2, 3
        ),
        cancel_event=pipeline.cancel_event,
        reached_commit=reached_commit,
        delete_mock=pipeline.delete_existing_transcription_data,
        insert_mock=pipeline.collection.batch.dynamic,
    )


def _lecture_unit_commit_target():
    pipeline = LectureUnitPipeline.__new__(LectureUnitPipeline)
    pipeline.cancel_event = threading.Event()
    pipeline.local = False
    pipeline.callback = MagicMock()
    pipeline.weaviate_client = MagicMock()
    pipeline.llm_embedding = MagicMock()
    pipeline.lecture_unit_collection = MagicMock()

    reached_commit = threading.Event()
    pipeline.llm_embedding.embed.side_effect = _signal_then_vector(reached_commit)

    lecture_unit = SimpleNamespace(
        course_id=1,
        lecture_id=2,
        lecture_unit_id=3,
        base_url="https://artemis.example",
        lecture_unit_summary="summary",
    )

    def run():
        with (
            patch(
                "iris.pipeline.lecture_unit_pipeline.LectureUnitSegmentSummaryPipeline"
            ) as segment_cls,
            patch(
                "iris.pipeline.lecture_unit_pipeline.LectureUnitSummaryPipeline"
            ) as summary_cls,
        ):
            segment_cls.return_value.return_value = ([], [])
            summary_cls.return_value.return_value = ("summary", [])
            LectureUnitPipeline.__call__.__wrapped__(
                pipeline, lecture_unit, initial_properties={}
            )

    return SimpleNamespace(
        run=run,
        commit_lock=lambda: ingestion_job_commit_lock(
            "https://artemis.example", 1, 2, 3
        ),
        cancel_event=pipeline.cancel_event,
        reached_commit=reached_commit,
        delete_mock=pipeline.lecture_unit_collection.data.delete_many,
        insert_mock=pipeline.lecture_unit_collection.data.insert,
        extra_not_called=[pipeline.lecture_unit_collection.query.fetch_objects],
    )


@pytest.mark.parametrize(
    "build_target, extra_not_called",
    [
        (_page_commit_target, []),
        (_transcription_commit_target, []),
        (_lecture_unit_commit_target, ["query.fetch_objects"]),
    ],
)
def test_cancelled_run_does_not_commit_after_waiting_for_commit_lock(
    build_target, extra_not_called
):
    target = build_target()
    errors = []

    def run():
        try:
            target.run()
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    with target.commit_lock():
        thread = threading.Thread(target=run)
        thread.start()
        # Embedding is the last step before the commit lock, so once it ran the
        # thread is about to block on the lock this test is holding.
        assert target.reached_commit.wait(timeout=5)
        target.cancel_event.set()

    thread.join(timeout=5)
    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], IngestionCancelledException)
    target.delete_mock.assert_not_called()
    target.insert_mock.assert_not_called()
    for not_called in extra_not_called:
        if not_called == "query.fetch_objects":
            target.extra_not_called[0].assert_not_called()

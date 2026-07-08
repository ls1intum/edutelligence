import json
import time
from pathlib import Path
from threading import Event
from typing import Optional

from iris.common.custom_exceptions import IngestionCancelledException
from iris.common.logging_config import get_logger
from iris.config import settings
from iris.domain.data.metrics.transcription_dto import (
    TranscriptionDTO,
    TranscriptionSegmentDTO,
)
from iris.domain.data.video_source_type import VideoSourceType
from iris.domain.ingestion.ingestion_pipeline_execution_dto import (
    IngestionPipelineExecutionDto,
)
from iris.domain.lecture.lecture_unit_dto import LectureUnitDTO
from iris.domain.variant.abstract_variant import find_variant
from iris.domain.variant.variant import Dep
from iris.pipeline import Pipeline
from iris.pipeline.lecture_ingestion_pipeline import LectureUnitPageIngestionPipeline
from iris.pipeline.lecture_unit_pipeline import LectureUnitPipeline
from iris.pipeline.transcription_ingestion_pipeline import (
    TranscriptionIngestionPipeline,
)
from iris.tracing import observe
from iris.vector_database.database import VectorDatabase
from iris.web.status.ingestion_status_callback import IngestionStatusCallback

logger = get_logger(__name__)


def _translate_transcription_exception_to_error_code(
    exc: BaseException,
) -> str:
    """Map any exception from heavy/light phases to a wire error code.

    YouTubeDownloadError already carries a structured ``error_code``;
    everything else collapses to TRANSCRIPTION_FAILED so Artemis can surface
    a generic "transcript unavailable" message with a retry affordance.
    """
    # pylint: disable=import-outside-toplevel
    from iris.pipeline.shared.transcription.youtube_utils import (
        YouTubeDownloadError,
    )

    if isinstance(exc, YouTubeDownloadError):
        return exc.error_code
    return "TRANSCRIPTION_FAILED"


def _needs_transcription_generation(dto: IngestionPipelineExecutionDto) -> bool:
    """Check if we need to generate a transcription (video exists, no transcript yet)."""
    return (
        settings.transcription.enabled
        and bool(dto.lecture_unit.video_link)
        and (
            dto.lecture_unit.transcription is None
            or dto.lecture_unit.transcription.segments is None
        )
    )


def _needs_slide_detection(dto: IngestionPipelineExecutionDto) -> bool:
    """Check if we have a raw transcript that still needs slide detection.

    A raw transcript (from a checkpoint after the heavy phase) has all
    slide_number == 0 (the Pydantic default).  An enriched transcript
    (from after the light phase) has real slide numbers (>= 1 or -1).
    """
    if not settings.transcription.enabled:
        return False
    if not dto.lecture_unit.video_link:
        return False
    transcription = dto.lecture_unit.transcription
    if transcription is None or transcription.segments is None:
        return False
    return all(seg.slide_number == 0 for seg in transcription.segments)


class LectureIngestionUpdatePipeline(Pipeline):
    """Unified pipeline: transcription generation + PDF/transcript ingestion.

    Artemis sends ONE request with all available data (video URL, PDF,
    existing transcription).  This pipeline decides what processing is
    needed and orchestrates everything:

    1. Transcription generation (if video URL present, no transcript yet)
       - Heavy phase: download video → extract audio → Whisper
       - Light phase: GPT Vision slide detection → alignment
    2. PDF page ingestion (if PDF present)
    3. Transcription ingestion (if transcript present — generated or provided)
    4. Lecture unit summary

    Retry skip logic:
    - Artemis re-sends whatever it already has from previous checkpoints.
    - If a raw transcript exists (heavy phase done), skip to light phase.
    - If an enriched transcript exists (light phase done), skip to ingestion.

    Checkpoints:
    - After heavy phase: raw transcript sent via callback ``final_result``
    - After light phase: enriched transcript sent via callback ``final_result``
    - Artemis saves these to PostgreSQL for retry.
    """

    PIPELINE_ID = "lecture_ingestion_update_pipeline"
    ROLES: set[str] = set()
    VARIANT_DEFS = [
        ("default", "Default", "Default lecture ingestion update variant."),
        ("advanced", "Advanced", "Advanced lecture ingestion update variant."),
    ]
    DEPENDENCIES = [
        Dep("lecture_unit_page_ingestion_pipeline", variant="same"),
        Dep("transcription_ingestion_pipeline"),
        Dep("lecture_unit_pipeline"),
        Dep("lecture_unit_segment_summary_pipeline"),
        Dep("lecture_unit_summary_pipeline"),
    ]

    def __init__(
        self,
        dto: IngestionPipelineExecutionDto,
        variant_id: str = "default",
        cancel_event: Optional[Event] = None,
    ):
        super().__init__(implementation_id=self.PIPELINE_ID)
        self.dto = dto
        self.variant_id = variant_id
        self.cancel_event = cancel_event
        self._is_local = bool(
            self.dto.settings and self.dto.settings.artemis_llm_selection == "LOCAL_AI"
        )

    def _check_cancellation(self, stage_name: str = None):
        """Check if job has been cancelled.

        Raises:
            IngestionCancelledException: If cancellation event is set.
        """
        if self.cancel_event is not None and self.cancel_event.is_set():
            lecture_unit_id = self.dto.lecture_unit.lecture_unit_id
            if stage_name:
                logger.info(
                    "[Lecture %d] Cancellation detected at stage: %s",
                    lecture_unit_id,
                    stage_name,
                )
            raise IngestionCancelledException(lecture_unit_id)

    @staticmethod
    def _send_heartbeats(
        callback: IngestionStatusCallback, count: int, reason: str
    ) -> None:
        logger.info("Skipping phase (%s) — sending %d heartbeat updates", reason, count)
        for _ in range(count):
            callback.update()

    def _log_phase_decisions(self, needs_generation: bool, needs_slides: bool) -> None:
        """Log why each ingestion phase will run or be skipped.

        A silently-dropped video (e.g. Artemis could not resolve the TUM-Live
        URL and sent video_link=null) makes ingestion finish in seconds with
        no transcription; this log makes that immediately visible.
        """
        unit = self.dto.lecture_unit
        transcription = unit.transcription
        logger.info(
            "[Lecture %d] Ingestion inputs | video_link=%s pdf=%s "
            "existing_transcript=%s → transcription_generation=%s slide_detection=%s",
            unit.lecture_unit_id,
            repr(unit.video_link) if unit.video_link else "MISSING",
            "present" if unit.pdf_file_base64 else "MISSING",
            (
                f"{len(transcription.segments)} segments"
                if transcription is not None and transcription.segments is not None
                else "none"
            ),
            needs_generation,
            needs_slides,
        )
        if not settings.transcription.enabled:
            logger.info(
                "[Lecture %d] Transcription disabled in application.yml",
                unit.lecture_unit_id,
            )
        elif not unit.video_link and transcription is None:
            logger.warning(
                "[Lecture %d] No video_link in the request — if this unit has a video "
                "source in Artemis, its URL could not be resolved there (e.g. TUM-Live "
                "slug rejected by the API); ingestion proceeds without transcription",
                unit.lecture_unit_id,
            )

    @observe(name="Lecture Ingestion Update Pipeline")
    def __call__(self):
        needs_generation = _needs_transcription_generation(self.dto)
        needs_slides = _needs_slide_detection(self.dto)
        self._log_phase_decisions(needs_generation, needs_slides)

        callback = IngestionStatusCallback(
            run_id=self.dto.settings.authentication_token,
            base_url=self.dto.settings.artemis_base_url,
            lecture_unit_id=self.dto.lecture_unit.lecture_unit_id,
        )

        try:
            # Check at start
            self._check_cancellation("pipeline_start")

            # ── Phase 1: Transcription generation (conditional) ──────────
            # Failures here get classified via the transcription error-code
            # translator (YouTubeDownloadError → structured code, else
            # TRANSCRIPTION_FAILED) so Artemis can render user-actionable
            # messages.
            try:
                if needs_generation:
                    self._check_cancellation("before_transcription_generation")
                    self._run_full_transcription(callback)
                elif needs_slides:
                    self._check_cancellation("before_slide_detection")
                    self._run_slide_detection_only(callback)
            except Exception as e:
                if isinstance(e, IngestionCancelledException):
                    callback.fail(
                        f"Job cancelled: {e.reason}",
                        code="INGESTION_CANCELLED",
                    )
                    raise

                logger.error(
                    "[Lecture %d] Transcription failed: %s",
                    self.dto.lecture_unit.lecture_unit_id,
                    e,
                    exc_info=True,
                )
                error_code = _translate_transcription_exception_to_error_code(e)
                callback.fail(str(e), exception=e, code=error_code)
                return

            # ── Phase 2: Ingestion (existing logic) ──────────────────────
            # Ingestion-phase failures (vector DB, PDF, summary) are NOT
            # transcription failures and must not be labeled as such.
            try:
                self._check_cancellation("before_ingestion")
                self._run_ingestion(callback)
            except IngestionCancelledException as e:
                callback.fail(
                    f"Job cancelled: {e.reason}",
                    code="INGESTION_CANCELLED",
                )
                raise

        except IngestionCancelledException:
            raise
        except Exception as e:
            logger.error(
                "[Lecture %d] Pipeline failed: %s",
                self.dto.lecture_unit.lecture_unit_id,
                e,
                exc_info=True,
            )
            callback.fail(str(e), exception=e)

    def _run_full_transcription(self, callback: IngestionStatusCallback) -> None:
        """Run heavy + light transcription phases with temp file management."""
        # pylint: disable=import-outside-toplevel
        from iris.pipeline.shared.transcription.heavy_pipeline import (
            HeavyTranscriptionPipeline,
        )
        from iris.pipeline.shared.transcription.light_pipeline import (
            LightTranscriptionPipeline,
        )
        from iris.pipeline.shared.transcription.temp_storage import (
            TranscriptionTempStorage,
        )

        lecture_unit_id = self.dto.lecture_unit.lecture_unit_id
        video_url = self.dto.lecture_unit.video_link

        logger.info(
            "[Lecture %d] Transcription phase starting | source_type=%s url=%s",
            lecture_unit_id,
            self.dto.lecture_unit.video_source_type,
            video_url,
        )
        with TranscriptionTempStorage(
            settings.transcription.temp_dir, lecture_unit_id=lecture_unit_id
        ) as storage:
            # Heavy phase: download → extract audio → Whisper
            self._check_cancellation()
            heavy_started = time.monotonic()
            heavy = HeavyTranscriptionPipeline(
                callback=callback,
                storage=storage,
                cancel_event=self.cancel_event,
            )
            raw_transcript = heavy(
                video_url,
                lecture_unit_id,
                video_source_type=self.dto.lecture_unit.video_source_type,
            )
            logger.info(
                "[Lecture %d] Heavy phase done in %.0fs (download + audio + Whisper)",
                lecture_unit_id,
                time.monotonic() - heavy_started,
            )

            # Checkpoint 1: complete the "Transcribing" stage with raw
            # transcript attached — one atomic HTTP call.
            checkpoint_1 = self._build_checkpoint(
                raw_transcript, lecture_unit_id, enriched=False
            )
            segment_count = len(raw_transcript.get("segments", []))
            callback.update(result=json.dumps(checkpoint_1))
            logger.info(
                "[Lecture %d] Checkpoint 1: raw transcript (%d segments)",
                lecture_unit_id,
                segment_count,
            )

            # Light phase: slide detection → alignment
            self._check_cancellation()
            light_started = time.monotonic()
            light = LightTranscriptionPipeline(
                callback=callback,
                video_path=storage.video_path,
                local=self._is_local,
                cancel_event=self.cancel_event,
            )
            aligned_segments = light(raw_transcript, lecture_unit_id)
            logger.info(
                "[Lecture %d] Light phase done in %.0fs (slide detection + alignment)",
                lecture_unit_id,
                time.monotonic() - light_started,
            )

            # Checkpoint 2: complete the "Aligning" stage with enriched
            # transcript attached — one atomic HTTP call.
            checkpoint_2 = self._build_checkpoint(
                raw_transcript,
                lecture_unit_id,
                enriched=True,
                aligned_segments=aligned_segments,
            )
            callback.update(result=json.dumps(checkpoint_2))
            logger.info(
                "[Lecture %d] Checkpoint 2: enriched transcript (%d segments)",
                lecture_unit_id,
                len(aligned_segments),
            )

            # Update DTO so ingestion phase can use the transcript
            self._update_dto_with_transcript(
                aligned_segments, raw_transcript.get("language", "en")
            )

    def _run_slide_detection_only(self, callback: IngestionStatusCallback) -> None:
        """Retry path: raw transcript exists, only need slide detection.

        Re-downloads the video for frame extraction, skips Whisper.
        """
        # pylint: disable=import-outside-toplevel
        from iris.pipeline.shared.transcription.light_pipeline import (
            LightTranscriptionPipeline,
        )
        from iris.pipeline.shared.transcription.temp_storage import (
            TranscriptionTempStorage,
        )
        from iris.pipeline.shared.transcription.video_utils import download_video
        from iris.pipeline.shared.transcription.youtube_utils import (
            download_youtube_video,
            validate_youtube_video,
        )

        lecture_unit_id = self.dto.lecture_unit.lecture_unit_id
        video_url = self.dto.lecture_unit.video_link
        existing = self.dto.lecture_unit.transcription

        # Convert existing DTO segments to the dict format our pipelines use
        raw_transcript = {
            "segments": [
                {
                    "start": seg.start_time,
                    "end": seg.end_time,
                    "text": seg.text,
                }
                for seg in existing.segments
            ],
            "language": existing.language,
        }

        with TranscriptionTempStorage(
            settings.transcription.temp_dir, lecture_unit_id=lecture_unit_id
        ) as storage:
            self._send_heartbeats(
                callback,
                3,
                "skipped heavy transcription stages",
            )

            # Re-download video for frame extraction
            self._check_cancellation()
            logger.info(
                "[Lecture %d] Re-downloading video for slide detection",
                lecture_unit_id,
            )
            video_source_type = self.dto.lecture_unit.video_source_type
            if video_source_type == VideoSourceType.YOUTUBE:
                ts = settings.transcription
                max_dur = ts.youtube_max_duration_seconds
                yt_timeout = ts.youtube_download_timeout_seconds
                validate_youtube_video(
                    video_url,
                    max_duration_seconds=max_dur,
                )
                download_youtube_video(
                    video_url,
                    Path(storage.video_path),
                    timeout=yt_timeout,
                )
            else:  # TUM_LIVE (default, includes None)
                download_video(
                    video_url,
                    storage.video_path,
                    timeout=settings.transcription.download_timeout_seconds,
                    lecture_unit_id=lecture_unit_id,
                )

            # Light phase: slide detection → alignment
            self._check_cancellation()
            light = LightTranscriptionPipeline(
                callback=callback,
                video_path=storage.video_path,
                local=self._is_local,
                cancel_event=self.cancel_event,
            )
            aligned_segments = light(raw_transcript, lecture_unit_id)

            # Checkpoint 2: complete "Aligning" stage with enriched transcript
            checkpoint_2 = self._build_checkpoint(
                raw_transcript,
                lecture_unit_id,
                enriched=True,
                aligned_segments=aligned_segments,
            )
            callback.update(result=json.dumps(checkpoint_2))
            logger.info(
                "[Lecture %d] Checkpoint 2: enriched transcript (%d segments)",
                lecture_unit_id,
                len(aligned_segments),
            )

            self._update_dto_with_transcript(aligned_segments, existing.language)

    def _run_ingestion(self, callback: IngestionStatusCallback) -> None:
        """Run the existing ingestion logic (PDF + transcription + summary)."""
        db = VectorDatabase()
        client = db.get_client()
        language = ""
        tokens = []

        variant_id = self.variant_id
        is_local = self._is_local

        # PDF page ingestion
        if (
            self.dto.lecture_unit.pdf_file_base64 is not None
            and self.dto.lecture_unit.pdf_file_base64 != ""
        ):
            self._check_cancellation("before_pdf_ingestion")
            logger.info(
                "[Lecture %d] Ingestion step 1/3: PDF page ingestion starting",
                self.dto.lecture_unit.lecture_unit_id,
            )
            variant = find_variant(
                LectureUnitPageIngestionPipeline.get_variants(), variant_id
            )
            page_content_pipeline = LectureUnitPageIngestionPipeline(
                client=client,
                dto=self.dto,
                callback=callback,
                variant=variant,
                local=is_local,
                cancel_event=self.cancel_event,
            )
            language, tokens_page_content_pipeline = page_content_pipeline()
            tokens += tokens_page_content_pipeline
        else:
            self._send_heartbeats(callback, 6, "missing PDF page ingestion")

        # Transcription ingestion
        if (
            self.dto.lecture_unit.transcription is not None
            and self.dto.lecture_unit.transcription.segments is not None
        ):
            self._check_cancellation("before_transcription_ingestion")
            logger.info(
                "[Lecture %d] Ingestion step 2/3: transcription ingestion starting "
                "(%d segments)",
                self.dto.lecture_unit.lecture_unit_id,
                len(self.dto.lecture_unit.transcription.segments),
            )
            transcription_pipeline = TranscriptionIngestionPipeline(
                client=client,
                dto=self.dto,
                callback=callback,
                local=is_local,
                cancel_event=self.cancel_event,
            )
            language, tokens_transcription_pipeline = transcription_pipeline()
            tokens += tokens_transcription_pipeline
        else:
            self._send_heartbeats(callback, 8, "missing transcription ingestion")

        # Lecture unit summary
        self._check_cancellation("before_lecture_unit_summary")
        logger.info(
            "[Lecture %d] Ingestion step 3/3: lecture unit summary starting",
            self.dto.lecture_unit.lecture_unit_id,
        )
        callback.update()
        lecture_unit_dto = LectureUnitDTO(
            course_id=self.dto.lecture_unit.course_id,
            course_name=self.dto.lecture_unit.course_name,
            course_description=self.dto.lecture_unit.course_description,
            course_language=language,
            lecture_id=self.dto.lecture_unit.lecture_id,
            lecture_name=self.dto.lecture_unit.lecture_name,
            lecture_unit_id=self.dto.lecture_unit.lecture_unit_id,
            lecture_unit_name=self.dto.lecture_unit.lecture_unit_name,
            lecture_unit_link=self.dto.lecture_unit.lecture_unit_link,
            video_link=self.dto.lecture_unit.video_link,
            base_url=self.dto.settings.artemis_base_url,
            release_date=self.dto.lecture_unit.release_date,
        )

        tokens += LectureUnitPipeline(
            local=is_local, callback=callback, cancel_event=self.cancel_event
        )(lecture_unit=lecture_unit_dto)
        callback.finish(
            display_page_numbers=self.dto.lecture_unit.display_page_numbers,
            tokens=tokens,
        )

    # ── Checkpoint helpers ───────────────────────────────────────────────

    @staticmethod
    def _build_checkpoint(
        raw_transcript: dict,
        lecture_unit_id: int,
        enriched: bool = False,
        aligned_segments: Optional[list] = None,
    ) -> dict:
        """Build a checkpoint dict for piggybacking on a done() callback.

        Args:
            raw_transcript: The Whisper result with "segments" and "language".
            lecture_unit_id: Lecture unit ID.
            enriched: If True, use aligned_segments (with slide numbers).
                      If False, build segments from raw transcript (slideNumber=0).
            aligned_segments: Aligned segments from the light pipeline.

        Returns:
            Dict matching the TranscriptionDTO JSON structure that Artemis
            can save to PostgreSQL and send back on retry.
        """
        if enriched and aligned_segments is not None:
            segments = aligned_segments
        else:
            segments = [
                {
                    "startTime": seg["start"],
                    "endTime": seg["end"],
                    "text": seg["text"].strip(),
                    "slideNumber": 0,
                }
                for seg in raw_transcript.get("segments", [])
            ]

        return {
            "lectureUnitId": lecture_unit_id,
            "language": raw_transcript.get("language", "en"),
            "segments": segments,
        }

    def _update_dto_with_transcript(
        self, aligned_segments: list, language: str
    ) -> None:
        """Update the DTO with the generated transcript so ingestion can use it."""
        self.dto.lecture_unit.transcription = TranscriptionDTO(
            language=language,
            segments=[
                TranscriptionSegmentDTO(
                    startTime=seg["startTime"],
                    endTime=seg["endTime"],
                    text=seg["text"],
                    slideNumber=seg["slideNumber"],
                )
                for seg in aligned_segments
            ],
        )

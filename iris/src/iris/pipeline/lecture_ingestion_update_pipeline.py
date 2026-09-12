import json
import time
import uuid
from pathlib import Path
from typing import Optional

from iris.common.ingestion_errors import IngestionStageError
from iris.common.ingestion_version import INGESTION_PIPELINE_VERSION
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
from iris.pipeline.ingestion_audit import IngestionAudit
from iris.pipeline.lecture_ingestion_pipeline import LectureUnitPageIngestionPipeline
from iris.pipeline.lecture_unit_pipeline import LectureUnitPipeline
from iris.pipeline.lecture_update_lock import lecture_update_lock
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
    ):
        super().__init__(implementation_id=self.PIPELINE_ID)
        self.dto = dto
        self.variant_id = variant_id
        self._is_local = bool(
            self.dto.settings and self.dto.settings.artemis_llm_selection == "LOCAL_AI"
        )

    @staticmethod
    def _send_heartbeats(
        callback: IngestionStatusCallback, count: int, reason: str
    ) -> None:
        logger.debug("Sending %d ingestion heartbeat updates for %s", count, reason)
        for _ in range(count):
            callback.update()

    @observe(name="Lecture Ingestion Update Pipeline")
    def __call__(self):
        self._run()

    def _run(self):
        """Run preprocessing, then serialize the Weaviate mutation phase."""
        # One id per run: every row this run writes carries it, and the write
        # paths sweep rows of other runs after a verified insert.
        self.dto.lecture_unit.ingestion_run_id = str(uuid.uuid4())
        self._stage_durations: dict[str, float] = {}
        self._run_started_at = time.monotonic()
        needs_generation = _needs_transcription_generation(self.dto)
        needs_slides = _needs_slide_detection(self.dto)

        callback = IngestionStatusCallback(
            run_id=self.dto.settings.authentication_token,
            base_url=self.dto.settings.artemis_base_url,
            lecture_unit_id=self.dto.lecture_unit.lecture_unit_id,
        )

        try:
            # Snapshot before transcription/slide processing. Lightweight metadata
            # webhooks may run during that expensive phase; the final replacement
            # uses this baseline to recognize and preserve those newer values.
            with lecture_update_lock(
                self.dto.settings.artemis_base_url,
                self.dto.lecture_unit.course_id,
                self.dto.lecture_unit.lecture_id,
                self.dto.lecture_unit.lecture_unit_id,
            ):
                initial_properties = LectureUnitPipeline.fetch_existing_properties(
                    VectorDatabase().get_client(),
                    self._build_lecture_unit_dto(),
                )

            # ── Phase 1: Transcription generation (conditional) ──────────
            # Failures here get classified via the transcription error-code
            # translator (YouTubeDownloadError → structured code, else
            # TRANSCRIPTION_FAILED) so Artemis can render user-actionable
            # messages.
            try:
                phase_started_at = time.monotonic()
                if needs_generation:
                    self._run_full_transcription(callback)
                    self._stage_durations["transcription-generation"] = (
                        time.monotonic() - phase_started_at
                    )
                elif needs_slides:
                    self._run_slide_detection_only(callback)
                    self._stage_durations["slide-detection"] = (
                        time.monotonic() - phase_started_at
                    )
            except Exception as e:
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
            with lecture_update_lock(
                self.dto.settings.artemis_base_url,
                self.dto.lecture_unit.course_id,
                self.dto.lecture_unit.lecture_id,
                self.dto.lecture_unit.lecture_unit_id,
            ):
                self._run_ingestion(callback, initial_properties)

        except IngestionStageError as e:
            logger.error(
                "[Lecture %d] Pipeline failed with code %s: %s",
                self.dto.lecture_unit.lecture_unit_id,
                e.error_code,
                e,
                exc_info=True,
            )
            callback.fail(str(e), exception=e, code=e.error_code, tokens=e.tokens)
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

        with TranscriptionTempStorage(
            settings.transcription.temp_dir, lecture_unit_id=lecture_unit_id
        ) as storage:
            # Heavy phase: download → extract audio → Whisper
            heavy = HeavyTranscriptionPipeline(
                callback=callback,
                storage=storage,
            )
            raw_transcript = heavy(
                video_url,
                lecture_unit_id,
                video_source_type=self.dto.lecture_unit.video_source_type,
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
            light = LightTranscriptionPipeline(
                callback=callback,
                video_path=storage.video_path,
                local=self._is_local,
            )
            aligned_segments = light(raw_transcript, lecture_unit_id)

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
            light = LightTranscriptionPipeline(
                callback=callback,
                video_path=storage.video_path,
                local=self._is_local,
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

    def _build_lecture_unit_dto(
        self, language: str = "", content_unchanged: bool = False
    ) -> LectureUnitDTO:
        chunk_counts = self.dto.lecture_unit.chunk_counts_by_page
        quality_flags = self.dto.lecture_unit.quality_flags
        return LectureUnitDTO(
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
            content_fingerprint=self.dto.lecture_unit.content_fingerprint,
            ingestion_run_id=self.dto.lecture_unit.ingestion_run_id,
            expected_chunk_counts_json=(
                json.dumps(chunk_counts) if chunk_counts is not None else None
            ),
            # Stamp the pipeline version only when the content pipeline actually ran this
            # generation (the same signal as expected_chunk_counts/quality_score). A pure
            # skip or the zero-LLM summary-reuse path leaves it None so ledger_value keeps
            # the stored version; otherwise a metadata-only re-dispatch would bump the
            # version without reprocessing and permanently disarm the once-per-version
            # quality requeue (the row would read as already on the current version while
            # its quality_score correctly stayed at the old, low value).
            pipeline_version=(
                INGESTION_PIPELINE_VERSION if chunk_counts is not None else None
            ),
            quality_score=self.dto.lecture_unit.quality_score,
            quality_flags_json=(
                json.dumps(quality_flags) if quality_flags is not None else None
            ),
            content_unchanged=content_unchanged,
        )

    def _run_ingestion(
        self, callback: IngestionStatusCallback, initial_properties: dict
    ) -> None:
        """Run the existing ingestion logic (PDF + transcription + summary)."""
        # _run initializes these; guard for callers that enter here directly.
        if not hasattr(self, "_stage_durations"):
            self._stage_durations = {}
            self._run_started_at = time.monotonic()
        db = VectorDatabase()
        client = db.get_client()
        language = ""
        tokens = []

        variant_id = self.variant_id
        is_local = self._is_local

        # PDF page ingestion
        has_pdf = bool(self.dto.lecture_unit.pdf_file_base64)
        pdf_skipped = False
        pdf_kept_previous = False
        if has_pdf:
            stage_started_at = time.monotonic()
            variant = find_variant(
                LectureUnitPageIngestionPipeline.get_variants(), variant_id
            )
            page_content_pipeline = LectureUnitPageIngestionPipeline(
                client=client,
                dto=self.dto,
                callback=callback,
                variant=variant,
                local=is_local,
            )
            language, tokens_page_content_pipeline = page_content_pipeline()
            tokens += tokens_page_content_pipeline
            pdf_skipped = page_content_pipeline.skipped
            pdf_kept_previous = page_content_pipeline.kept_previous_generation
            self._stage_durations["page-ingestion"] = (
                time.monotonic() - stage_started_at
            )
        else:
            self._send_heartbeats(callback, 6, "missing PDF page ingestion")

        # Transcription ingestion
        has_transcript = (
            self.dto.lecture_unit.transcription is not None
            and self.dto.lecture_unit.transcription.segments is not None
        )
        transcript_skipped = False
        if has_transcript:
            stage_started_at = time.monotonic()
            transcription_pipeline = TranscriptionIngestionPipeline(
                client=client, dto=self.dto, callback=callback, local=is_local
            )
            language, tokens_transcription_pipeline = transcription_pipeline()
            tokens += tokens_transcription_pipeline
            transcript_skipped = transcription_pipeline.skipped
            self._stage_durations["transcript-ingestion"] = (
                time.monotonic() - stage_started_at
            )
        else:
            self._send_heartbeats(callback, 8, "missing transcription ingestion")

        # Lecture unit summary. When every content sub-pipeline structurally
        # skipped (or kept its previous generation), the stored unit summary
        # provably still fits the content and may be reused.
        content_unchanged = (not has_pdf or pdf_skipped or pdf_kept_previous) and (
            not has_transcript or transcript_skipped
        )
        callback.update()
        stage_started_at = time.monotonic()
        lecture_unit_dto = self._build_lecture_unit_dto(language, content_unchanged)

        tokens += LectureUnitPipeline(local=is_local, callback=callback)(
            lecture_unit=lecture_unit_dto,
            initial_properties=initial_properties,
        )
        self._stage_durations["unit-summary"] = time.monotonic() - stage_started_at

        # FINISHED is a verified claim: read back the index and compare it
        # against the request inputs before certifying the run. Report the audit
        # as its own stage so the client can show "Verifying" rather than staying
        # on "Indexing" through the final read-back.
        callback.update(stage_name="audit")
        stage_started_at = time.monotonic()
        IngestionAudit.for_client(client).verify(self.dto)
        self._stage_durations["audit"] = time.monotonic() - stage_started_at

        stage_summary = " ".join(
            f"{stage}={duration:.1f}s"
            for stage, duration in self._stage_durations.items()
        )
        logger.info(
            "run-summary unit=%d run=%s total=%.1fs pdf_skipped=%s "
            "transcript_skipped=%s kept_previous=%s quality=%s | %s",
            self.dto.lecture_unit.lecture_unit_id,
            self.dto.lecture_unit.ingestion_run_id,
            time.monotonic() - self._run_started_at,
            pdf_skipped,
            transcript_skipped,
            pdf_kept_previous,
            self.dto.lecture_unit.quality_score,
            stage_summary,
        )

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

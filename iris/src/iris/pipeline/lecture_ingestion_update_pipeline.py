import json
from typing import List

from iris.common.logging_config import get_logger
from iris.config import settings
from iris.domain.data.metrics.transcription_dto import (
    TranscriptionDTO,
    TranscriptionSegmentDTO,
)
from iris.domain.ingestion.ingestion_pipeline_execution_dto import (
    IngestionPipelineExecutionDto,
)
from iris.domain.lecture.lecture_unit_dto import LectureUnitDTO
from iris.domain.variant.lecture_ingestion_update_variant import (
    LectureIngestionUpdateVariant,
)
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


def _any_transcription_stage_needed(dto: IngestionPipelineExecutionDto) -> bool:
    """True if the callback should include transcription generation stages."""
    return _needs_transcription_generation(dto) or _needs_slide_detection(dto)


class LectureIngestionUpdatePipeline(Pipeline[LectureIngestionUpdateVariant]):
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

    def __init__(self, dto: IngestionPipelineExecutionDto):
        super().__init__()
        self.dto = dto

    @observe(name="Lecture Ingestion Update Pipeline")
    def __call__(self):
        needs_generation = _needs_transcription_generation(self.dto)
        needs_slides = _needs_slide_detection(self.dto)
        include_transcription = needs_generation or needs_slides

        callback = IngestionStatusCallback(
            run_id=self.dto.settings.authentication_token,
            base_url=self.dto.settings.artemis_base_url,
            initial_stages=self.dto.initial_stages,
            lecture_unit_id=self.dto.lecture_unit.lecture_unit_id,
            include_transcription_stages=include_transcription,
        )

        try:
            # ── Phase 1: Transcription generation (conditional) ──────────
            if needs_generation:
                self._run_full_transcription(callback)
            elif needs_slides:
                self._run_slide_detection_only(callback)

            # ── Phase 2: Ingestion (existing logic) ──────────────────────
            self._run_ingestion(callback)

        except Exception as e:
            logger.error(
                "[Lecture %d] Pipeline failed: %s",
                self.dto.lecture_unit.lecture_unit_id,
                e,
                exc_info=True,
            )
            callback.error(str(e), exception=e)

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
            raw_transcript = heavy(video_url, lecture_unit_id)

            # Checkpoint 1: complete the "Transcribing" stage with raw
            # transcript attached — one atomic HTTP call.
            checkpoint_1 = self._build_checkpoint(
                raw_transcript, lecture_unit_id, enriched=False
            )
            segment_count = len(raw_transcript.get("segments", []))
            callback.done(
                f"Transcribed {segment_count} segments",
                final_result=json.dumps(checkpoint_1),
            )
            logger.info(
                "[Lecture %d] Checkpoint 1: raw transcript (%d segments)",
                lecture_unit_id,
                segment_count,
            )

            # Light phase: slide detection → alignment
            light = LightTranscriptionPipeline(
                callback=callback,
                video_path=storage.video_path,
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
            callback.done(
                "Alignment complete",
                final_result=json.dumps(checkpoint_2),
            )
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
        from iris.pipeline.shared.transcription.video_utils import (
            download_video,
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
            # Skip heavy stages (download, extract, transcribe)
            callback.skip("Skipped (transcript from checkpoint)")
            callback.skip("Skipped (transcript from checkpoint)")
            callback.skip("Skipped (transcript from checkpoint)")

            # Re-download video for frame extraction
            logger.info(
                "[Lecture %d] Re-downloading video for slide detection",
                lecture_unit_id,
            )
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
            )
            aligned_segments = light(raw_transcript, lecture_unit_id)

            # Checkpoint 2: complete "Aligning" stage with enriched transcript
            checkpoint_2 = self._build_checkpoint(
                raw_transcript,
                lecture_unit_id,
                enriched=True,
                aligned_segments=aligned_segments,
            )
            callback.done(
                "Alignment complete",
                final_result=json.dumps(checkpoint_2),
            )
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

        # PDF page ingestion
        if (
            self.dto.lecture_unit.pdf_file_base64 is not None
            and self.dto.lecture_unit.pdf_file_base64 != ""
        ):
            page_content_pipeline = LectureUnitPageIngestionPipeline(
                client=client, dto=self.dto, callback=callback
            )
            language, tokens_page_content_pipeline = page_content_pipeline()
            tokens += tokens_page_content_pipeline
        else:
            callback.in_progress("skipping slide removal")
            callback.done()
            callback.in_progress("skipping slide interpretation")
            callback.done()
            callback.in_progress("skipping slide ingestion")
            callback.done()

        # Transcription ingestion
        if (
            self.dto.lecture_unit.transcription is not None
            and self.dto.lecture_unit.transcription.segments is not None
        ):
            transcription_pipeline = TranscriptionIngestionPipeline(
                client=client, dto=self.dto, callback=callback
            )
            language, tokens_transcription_pipeline = transcription_pipeline()
            tokens += tokens_transcription_pipeline
        else:
            callback.in_progress("skipping transcription removal")
            callback.done()
            callback.in_progress("skipping transcription chunking")
            callback.done()
            callback.in_progress("skipping transcription summarization")
            callback.done()
            callback.in_progress("skipping transcription ingestion")
            callback.done()

        # Lecture unit summary
        callback.in_progress("Ingesting lecture unit summary into vector database")
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
        )

        is_local = self.dto.settings is not None and self.dto.settings.is_local()
        tokens += LectureUnitPipeline(local=is_local)(lecture_unit=lecture_unit_dto)
        callback.done(
            "Ingested lecture unit summary into vector database",
            tokens=tokens,
        )

    # ── Checkpoint helpers ───────────────────────────────────────────────

    @staticmethod
    def _build_checkpoint(
        raw_transcript: dict,
        lecture_unit_id: int,
        enriched: bool = False,
        aligned_segments: list = None,
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

    @classmethod
    def get_variants(cls) -> List[LectureIngestionUpdateVariant]:
        return [
            LectureIngestionUpdateVariant(
                variant_id="default",
                name="Default",
                description="Default lecture ingestion update variant using efficient models "
                "for processing and embeddings.",
                cloud_chat_model="gpt-5-mini",
                local_chat_model="gpt-oss:120b",
                embedding_model="text-embedding-3-small",
            ),
            LectureIngestionUpdateVariant(
                variant_id="advanced",
                name="Advanced",
                description="Advanced lecture ingestion update variant using higher-quality models "
                "for improved accuracy.",
                cloud_chat_model="gpt-5.2",
                local_chat_model="gpt-oss:120b",
                embedding_model="text-embedding-3-large",
            ),
        ]

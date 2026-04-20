"""Heavy transcription pipeline: download video, extract audio, transcribe.

This is the resource-intensive phase of transcription. It runs FFmpeg for
video download and audio extraction, then sends audio chunks to the Whisper
API in parallel.  The result is a raw transcript (segments with timestamps
but no slide numbers).
"""

import os
from pathlib import Path
from typing import Any, Dict

from iris.common.logging_config import get_logger
from iris.config import settings
from iris.domain.data.video_source_type import VideoSourceType
from iris.pipeline.shared.transcription.temp_storage import TranscriptionTempStorage
from iris.pipeline.shared.transcription.video_utils import download_video, extract_audio
from iris.pipeline.shared.transcription.whisper_client import WhisperClient
from iris.pipeline.shared.transcription.youtube_utils import (
    download_youtube_video,
    validate_youtube_video,
)
from iris.tracing import observe
from iris.web.status.status_update import StatusCallback

logger = get_logger(__name__)


class HeavyTranscriptionPipeline:
    """Download video, extract audio, and transcribe with Whisper.

    This pipeline is sequential and CPU/network-intensive:
    1. Download HLS video stream via FFmpeg
    2. Extract audio track from video
    3. Split audio into chunks and transcribe with Whisper API

    It does NOT create or manage temp storage — the caller provides a
    ``TranscriptionTempStorage`` whose lifecycle spans the full pipeline
    (heavy + light + ingestion).
    """

    def __init__(
        self,
        callback: StatusCallback,
        storage: TranscriptionTempStorage,
    ):
        self.callback = callback
        self.storage = storage
        self.whisper_client = WhisperClient(
            model=settings.transcription.whisper_model,
            chunk_duration=settings.transcription.chunk_duration_seconds,
            max_retries=settings.transcription.whisper_max_retries,
            max_workers=settings.transcription.whisper_max_workers,
            request_timeout=settings.transcription.whisper_request_timeout_seconds,
            no_speech_threshold=settings.transcription.no_speech_filter_threshold,
        )

    @observe(name="Heavy Transcription Pipeline")
    def __call__(
        self,
        video_url: str,
        lecture_unit_id: int,
        video_source_type: VideoSourceType = VideoSourceType.TUM_LIVE,
    ) -> Dict[str, Any]:
        """Run the heavy pipeline.

        Args:
            video_url: URL of the video to download. For TUM_LIVE this is a
                direct HLS stream URL; for YOUTUBE it is a YouTube watch/share
                URL.
            lecture_unit_id: For logging and Whisper log prefixing.
            video_source_type: Determines which download path to use.
                Defaults to ``TUM_LIVE`` for backward compatibility.

        Returns:
            Dict with "segments" (list of dicts with start/end/text)
            and "language" (detected language code).

        Raises:
            RuntimeError: If any step fails (FFmpeg or Whisper).
            YouTubeDownloadError: If the YouTube branch fails validation or
                download.
        """
        prefix = f"[Lecture {lecture_unit_id}]"

        # Stage 1: Download video
        self.callback.in_progress("Downloading video...")
        logger.info("%s Downloading video to %s", prefix, self.storage.video_path)
        if video_source_type == VideoSourceType.YOUTUBE:
            yt_cfg = settings.transcription
            metadata = validate_youtube_video(
                video_url,
                max_duration_seconds=yt_cfg.youtube_max_duration_seconds,
            )
            logger.info(
                "%s YouTube metadata OK: title=%r duration=%ss",
                prefix,
                metadata.get("title"),
                metadata.get("duration"),
            )
            download_youtube_video(
                video_url,
                Path(self.storage.video_path),
                timeout=yt_cfg.youtube_download_timeout_seconds,
            )
        else:  # TUM_LIVE (default)
            download_video(
                video_url,
                self.storage.video_path,
                timeout=settings.transcription.download_timeout_seconds,
                lecture_unit_id=lecture_unit_id,
            )
        size_mb = os.path.getsize(self.storage.video_path) / (1024 * 1024)
        self.callback.done(f"Video downloaded ({size_mb:.0f} MB)")
        logger.info("%s Video downloaded: %.0f MB", prefix, size_mb)

        # Stage 2: Extract audio
        self.callback.in_progress("Extracting audio from video...")
        extract_audio(
            self.storage.video_path,
            self.storage.audio_path,
            timeout=settings.transcription.extract_audio_timeout_seconds,
            lecture_unit_id=lecture_unit_id,
        )
        audio_mb = os.path.getsize(self.storage.audio_path) / (1024 * 1024)
        self.callback.done(f"Audio extracted ({audio_mb:.0f} MB)")
        logger.info("%s Audio extracted: %.0f MB", prefix, audio_mb)

        # Stage 3: Transcribe with Whisper
        # Note: the orchestrator calls done() for this stage so it can
        # attach the checkpoint data atomically in the same HTTP call.
        self.callback.in_progress("Transcribing audio with Whisper...")

        def _on_chunk_complete(chunks_done: int, total_chunks: int) -> None:
            """Heartbeat: notify Artemis after each Whisper chunk completes.

            This keeps the Hazelcast job token alive and gives the UI
            accurate progress during long transcriptions.
            """
            self.callback.in_progress(
                f"Transcribing audio with Whisper ({chunks_done}/{total_chunks} chunks)"
            )

        transcription = self.whisper_client.transcribe(
            self.storage.audio_path,
            lecture_unit_id=lecture_unit_id,
            on_chunk_complete=_on_chunk_complete,
        )
        segment_count = len(transcription.get("segments", []))
        logger.info(
            "%s Transcription complete: %d segments, language=%s",
            prefix,
            segment_count,
            transcription.get("language", "unknown"),
        )

        return transcription

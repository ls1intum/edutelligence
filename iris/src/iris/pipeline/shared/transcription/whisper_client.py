"""Whisper API client for audio transcription.

Handles chunking, parallel upload, retry with linear backoff,
no-speech filtering, and language detection.  Configuration for
the Whisper endpoint/key is loaded from llm_config.yml via LlmManager.
"""

import os
import time
from concurrent.futures import as_completed
from typing import Any, Dict, List, Optional, Tuple

import ffmpeg  # type: ignore
import requests

from iris.common.logging_config import get_logger
from iris.llm.external.whisper import AzureWhisperModel, OpenAIWhisperModel
from iris.llm.llm_manager import LlmManager
from iris.pipeline.shared.transcription.audio_utils import split_audio_ffmpeg
from iris.tracing import TracedThreadPoolExecutor, observe

logger = get_logger(__name__)


def _audio_duration(audio_path: str) -> float:
    """Return the duration of an audio file in seconds via ffprobe."""
    try:
        probe = ffmpeg.probe(audio_path)
        return float(probe["format"]["duration"])
    except ffmpeg.Error as e:  # type: ignore[attr-defined]
        raise RuntimeError(f"ffprobe failed for '{audio_path}': {e.stderr}") from e
    except (KeyError, ValueError) as e:
        raise RuntimeError(f"Could not read duration from '{audio_path}': {e}") from e


class WhisperClient:
    """Client for transcribing audio using the Whisper API.

    Supports both Azure Whisper and direct OpenAI Whisper.
    Automatically splits long audio into chunks, transcribes them
    in parallel, applies no-speech filtering, and detects language.
    """

    def __init__(
        self,
        model: str = "whisper",
        chunk_duration: int = 900,
        max_retries: int = 6,
        max_workers: int = 2,
        request_timeout: int = 300,
        no_speech_threshold: float = 0.8,
    ):
        """
        Args:
            model: Model ID to look up in llm_config.yml.
            chunk_duration: Audio chunk duration in seconds.
            max_retries: Max retry attempts for transient failures.
            max_workers: Max parallel chunk uploads.
            request_timeout: Timeout per Whisper API request in seconds.
            no_speech_threshold: Segments with no_speech_prob above this are discarded.
        """
        self.llm = LlmManager().get_llm_by_id(model)
        if self.llm is None:
            raise ValueError(f"Model '{model}' not found in llm_config.yml")
        if not isinstance(self.llm, (AzureWhisperModel, OpenAIWhisperModel)):
            raise ValueError(
                f"Model '{model}' is not a Whisper model (expected azure_whisper "
                f"or openai_whisper, got {type(self.llm).__name__})"
            )

        self.chunk_duration = chunk_duration
        self.max_retries = max_retries
        self.max_workers = max_workers
        self.request_timeout = request_timeout
        self.no_speech_threshold = no_speech_threshold
        self.provider_name = (
            "Azure" if isinstance(self.llm, AzureWhisperModel) else "OpenAI"
        )

    def _get_request_params(self) -> Tuple[str, Dict[str, str], Dict[str, str]]:
        """Build provider-specific URL, headers, and form data for the Whisper API."""
        if isinstance(self.llm, AzureWhisperModel):
            url = (
                f"{self.llm.endpoint}/openai/deployments/{self.llm.azure_deployment}"
                f"/audio/transcriptions?api-version={self.llm.api_version}"
            )
            headers = {"api-key": self.llm.api_key}
            data = {
                "response_format": "verbose_json",
                "timestamp_granularities[]": "segment",
            }
        else:  # OpenAIWhisperModel
            url = "https://api.openai.com/v1/audio/transcriptions"
            headers = {"Authorization": f"Bearer {self.llm.api_key}"}
            data = {
                "model": self.llm.model,
                "response_format": "verbose_json",
                "timestamp_granularities[]": "segment",
            }

        return url, headers, data

    def _get_retry_wait_time(self, attempt: int) -> int:
        """Linear backoff: Azure 30/60/90s, OpenAI 10/20/30s."""
        if isinstance(self.llm, AzureWhisperModel):
            return 30 * (attempt + 1)
        return 10 * (attempt + 1)

    @observe(name="Transcribe Audio")
    def transcribe(
        self, audio_path: str, lecture_unit_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Transcribe an audio file using Whisper.

        Splits long audio into chunks, transcribes in parallel,
        applies no-speech filtering, and detects language.

        Args:
            audio_path: Path to the audio file.
            lecture_unit_id: For log prefixing.

        Returns:
            Dict with:
            - "segments": list of dicts with "start", "end", "text" keys
            - "language": detected language code ("en" or "de")

        Raises:
            RuntimeError: If any chunk fails after all retries.
        """
        uid = os.path.splitext(os.path.basename(audio_path))[0]
        chunks_dir = os.path.join(os.path.dirname(audio_path), f"chunks_{uid}")
        chunk_paths = split_audio_ffmpeg(
            audio_path, chunks_dir, chunk_duration=self.chunk_duration
        )

        # Pre-calculate cumulative offsets so chunks can be transcribed in parallel.
        offsets: List[float] = []
        cumulative = 0.0
        for chunk_path in chunk_paths:
            offsets.append(cumulative)
            cumulative += _audio_duration(chunk_path)

        total = len(chunk_paths)
        results: List[Optional[List[Dict[str, Any]]]] = [None] * total
        # Weighted language votes: language -> total surviving segments.
        # Chunks with 0 surviving segments cast no vote.
        language_votes: Dict[str, int] = {}

        with TracedThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(
                    self._transcribe_chunk, chunk_path, i, total, lecture_unit_id
                ): i
                for i, chunk_path in enumerate(chunk_paths)
            }
            for future in as_completed(futures):
                i = futures[future]
                offset = offsets[i]
                segments, language = future.result()
                if language is not None and len(segments) > 0:
                    language_votes[language] = language_votes.get(language, 0) + len(
                        segments
                    )
                results[i] = [
                    {
                        "start": offset + seg["start"],
                        "end": offset + seg["end"],
                        "text": seg["text"],
                    }
                    for seg in segments
                ]

        language_map = {"english": "en", "german": "de"}
        winner = (
            max(language_votes, key=language_votes.__getitem__)
            if language_votes
            else None
        )
        detected_language = (
            language_map.get(winner, "en") if winner is not None else "en"
        )
        if winner is not None and winner not in language_map:
            prefix = _log_prefix(lecture_unit_id)
            logger.warning(
                "%s Detected language '%s' not supported, falling back to english",
                prefix,
                winner,
            )

        all_segments = [
            seg for chunk_segs in results if chunk_segs for seg in chunk_segs
        ]
        return {"segments": all_segments, "language": detected_language}

    def _transcribe_chunk(
        self,
        chunk_path: str,
        chunk_index: int,
        total_chunks: int,
        lecture_unit_id: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Transcribe a single chunk with retry logic.

        Returns:
            Tuple of (filtered_segments, language).
        """
        url, headers, data = self._get_request_params()
        prefix = _log_prefix(lecture_unit_id)

        for attempt in range(self.max_retries):
            with open(chunk_path, "rb") as f:
                logger.info(
                    "%s %s uploading chunk %d/%d",
                    prefix,
                    self.provider_name,
                    chunk_index + 1,
                    total_chunks,
                )

                try:
                    response = requests.post(
                        url=url,
                        headers=headers,
                        files={"file": (os.path.basename(chunk_path), f, "audio/mp3")},
                        data=data,
                        timeout=self.request_timeout,
                    )

                    if response.status_code == 429:
                        wait = self._get_retry_wait_time(attempt)
                        logger.warning(
                            "%s Chunk %d/%d rate limited (429) — retrying in %ds "
                            "(attempt %d/%d)",
                            prefix,
                            chunk_index + 1,
                            total_chunks,
                            wait,
                            attempt + 1,
                            self.max_retries,
                        )
                        time.sleep(wait)
                        continue

                    response.raise_for_status()
                    body = response.json()
                    raw_segments = body.get("segments", [])
                    language = body.get("language")

                    # Filter non-speech segments (silence, background noise).
                    segments = [
                        seg
                        for seg in raw_segments
                        if seg.get("no_speech_prob", 0.0) <= self.no_speech_threshold
                    ]
                    filtered_count = len(raw_segments) - len(segments)
                    if filtered_count:
                        logger.info(
                            "%s Chunk %d/%d: filtered %d/%d segments "
                            "(no_speech_prob > %.2f)",
                            prefix,
                            chunk_index + 1,
                            total_chunks,
                            filtered_count,
                            len(raw_segments),
                            self.no_speech_threshold,
                        )

                    logger.info(
                        "%s Chunk %d/%d done: %d segments, language=%s",
                        prefix,
                        chunk_index + 1,
                        total_chunks,
                        len(segments),
                        language,
                    )
                    return segments, language

                except requests.RequestException as e:
                    logger.error(
                        "%s %s Whisper failed on chunk %d/%d: %s",
                        prefix,
                        self.provider_name,
                        chunk_index + 1,
                        total_chunks,
                        e,
                    )
                    if attempt == self.max_retries - 1:
                        raise RuntimeError(
                            f"{self.provider_name} Whisper failed after "
                            f"{self.max_retries} retries: {e}"
                        ) from e

                    wait = self._get_retry_wait_time(attempt)
                    logger.warning(
                        "%s Chunk %d/%d retrying in %ds (attempt %d/%d)",
                        prefix,
                        chunk_index + 1,
                        total_chunks,
                        wait,
                        attempt + 1,
                        self.max_retries,
                    )
                    time.sleep(wait)

        raise RuntimeError(
            f"{self.provider_name} Whisper too many retries for chunk {chunk_path}"
        )


def _log_prefix(lecture_unit_id: Optional[int]) -> str:
    return (
        f"[Lecture {lecture_unit_id}]" if lecture_unit_id is not None else "[Lecture ?]"
    )

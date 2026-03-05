"""Whisper API client for audio transcription."""

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Tuple

import ffmpeg  # type: ignore
import requests

from iris.common.logging_config import get_logger
from iris.llm.external.whisper import AzureWhisperModel, OpenAIWhisperModel
from iris.llm.llm_manager import LlmManager
from iris.pipeline.transcription.utils.audio_utils import split_audio_ffmpeg
from iris.tracing import observe

logger = get_logger(__name__)


def get_audio_duration(audio_path: str) -> float:
    """Get the duration of an audio file using ffprobe."""
    probe = ffmpeg.probe(audio_path)
    return float(probe["format"]["duration"])


class WhisperClient:
    """
    Client for transcribing audio using Whisper API.

    Supports both Azure Whisper and OpenAI Whisper providers.
    Configuration is loaded from llm_config.yml.

    Automatically handles audio chunking for long files and includes
    retry logic with exponential backoff for rate limiting.
    """

    def __init__(
        self,
        model: str = "whisper",
        chunk_duration: int = 900,
        max_retries: int = 6,
        max_workers: int = 2,
    ):
        """
        Initialize the Whisper client.

        Args:
            model: Model name to look up in llm_config.yml (default: "whisper").
            chunk_duration: Duration of audio chunks in seconds (default: 900 = 15 min).
            max_retries: Maximum retry attempts for rate limiting.
            max_workers: Max parallel chunk uploads (default: 2).
        """
        self.llm = LlmManager().get_llm_by_id(model)
        if not isinstance(self.llm, (AzureWhisperModel, OpenAIWhisperModel)):
            raise ValueError(f"Model '{model}' is not a Whisper model")

        self.chunk_duration = chunk_duration
        self.max_retries = max_retries
        self.max_workers = max_workers
        self.provider_name = (
            "Azure" if isinstance(self.llm, AzureWhisperModel) else "OpenAI"
        )

    def _get_request_params(self) -> Tuple[str, Dict[str, str], Dict[str, str]]:
        """
        Build provider-specific request parameters for Whisper API.

        Returns:
            Tuple of (url, headers, data_payload).
        """
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
        """
        Get provider-specific retry wait time for rate limiting.

        Uses exponential backoff: base_time * (attempt + 1).

        Args:
            attempt: Current attempt number (0-indexed).

        Returns:
            Wait time in seconds.
        """
        if isinstance(self.llm, AzureWhisperModel):
            return 30 * (attempt + 1)
        else:  # OpenAIWhisperModel
            return 10 * (attempt + 1)

    @observe(name="Transcribe Audio")
    def transcribe(
        self, audio_path: str, lecture_unit_id: int | None = None
    ) -> Dict[str, Any]:
        """
        Transcribe an audio file using Whisper API.

        Long audio files are automatically split into chunks, then transcribed
        in parallel using up to max_workers concurrent API requests.

        Args:
            audio_path: Path to the audio file.
            lecture_unit_id: Used for log prefixing.

        Returns:
            Dict with "segments" key containing list of transcript segments.
            Each segment has "start", "end", and "text" keys.

        Raises:
            RuntimeError: If transcription fails after all retries.
        """
        uid = os.path.splitext(os.path.basename(audio_path))[0]
        chunks_dir = os.path.join(os.path.dirname(audio_path), f"chunks_{uid}")
        chunk_paths = split_audio_ffmpeg(
            audio_path, chunks_dir, chunk_duration=self.chunk_duration
        )

        # Pre-calculate cumulative offsets so chunks can be transcribed in parallel
        offsets: List[float] = []
        cumulative = 0.0
        for chunk_path in chunk_paths:
            offsets.append(cumulative)
            cumulative += get_audio_duration(chunk_path)

        total = len(chunk_paths)
        results: List[List[Dict[str, Any]]] = [None] * total  # type: ignore[list-item]

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(
                    self._transcribe_chunk, chunk_path, i, total, lecture_unit_id
                ): i
                for i, chunk_path in enumerate(chunk_paths)
            }
            for future in as_completed(futures):
                i = futures[future]
                offset = offsets[i]
                segments = future.result()
                results[i] = [
                    {
                        "start": offset + seg["start"],
                        "end": offset + seg["end"],
                        "text": seg["text"],
                    }
                    for seg in segments
                ]

        all_segments = [seg for chunk_segs in results for seg in chunk_segs]
        return {"segments": all_segments}

    def _transcribe_chunk(
        self,
        chunk_path: str,
        chunk_index: int,
        total_chunks: int,
        lecture_unit_id: int | None = None,
    ) -> List[Dict[str, Any]]:
        """
        Transcribe a single audio chunk with retry logic.

        Args:
            chunk_path: Path to the audio chunk.
            chunk_index: Index of this chunk (for logging).
            total_chunks: Total number of chunks (for logging).
            lecture_unit_id: Used for log prefixing.

        Returns:
            List of segment dicts with "start", "end", "text" keys.

        Raises:
            RuntimeError: If transcription fails after all retries.
        """
        url, headers, data = self._get_request_params()
        prefix = (
            f"[Lecture {lecture_unit_id}]"
            if lecture_unit_id is not None
            else "[Lecture ?]"
        )

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
                        timeout=120,
                    )

                    if response.status_code == 429:
                        wait = self._get_retry_wait_time(attempt)
                        logger.warning(
                            "%s Chunk %d/%d rate limited (429) - retrying in %ds (attempt %d/%d)",
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
                    segments = response.json().get("segments", [])
                    logger.info(
                        "%s Chunk %d/%d done: %d segments",
                        prefix,
                        chunk_index + 1,
                        total_chunks,
                        len(segments),
                    )
                    return segments

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

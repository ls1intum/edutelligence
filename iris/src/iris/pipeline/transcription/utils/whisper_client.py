"""Whisper API client for audio transcription."""

import os
import time
from typing import Any, Dict, List, Tuple

import ffmpeg  # type: ignore
import requests

from iris.common.logging_config import get_logger
from iris.config import load_whisper_config
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
    ):
        """
        Initialize the Whisper client.

        Args:
            model: Model name to look up in llm_config.yml (default: "whisper").
            chunk_duration: Duration of audio chunks in seconds (default: 900 = 15 min).
            max_retries: Maximum retry attempts for rate limiting.
        """
        self.config = load_whisper_config(model)
        self.chunk_duration = chunk_duration
        self.max_retries = max_retries

        self.llm_type = self.config.get("type", "")
        if self.llm_type not in ("azure_whisper", "openai_whisper"):
            raise ValueError(f"Unsupported Whisper type: {self.llm_type}")

        self.provider_name = self.llm_type.replace("_whisper", "").title()

    def _get_request_params(self) -> Tuple[str, Dict[str, str], Dict[str, str]]:
        """
        Build provider-specific request parameters for Whisper API.

        Returns:
            Tuple of (url, headers, data_payload).
        """
        if self.llm_type == "azure_whisper":
            endpoint = self.config.get("endpoint", "")
            api_version = self.config.get("api_version", "")
            azure_deployment = self.config.get("azure_deployment", "whisper")
            url = (
                f"{endpoint}/openai/deployments/{azure_deployment}/audio/"
                f"transcriptions?api-version={api_version}"
            )
            headers = {"api-key": self.config.get("api_key", "")}
            data = {
                "response_format": "verbose_json",
                "timestamp_granularities[]": "segment",
            }
        else:  # openai_whisper
            url = "https://api.openai.com/v1/audio/transcriptions"
            api_key = self.config.get("api_key", "")
            headers = {"Authorization": f"Bearer {api_key}"}
            data = {
                "model": self.config.get("model", "whisper-1"),
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
        if self.llm_type == "azure_whisper":
            return 30 * (attempt + 1)
        else:  # openai_whisper
            return 10 * (attempt + 1)

    @observe(name="Transcribe Audio")
    def transcribe(self, audio_path: str) -> Dict[str, Any]:
        """
        Transcribe an audio file using Whisper API.

        Long audio files are automatically split into chunks.

        Args:
            audio_path: Path to the audio file.

        Returns:
            Dict with "segments" key containing list of transcript segments.
            Each segment has "start", "end", and "text" keys.

        Raises:
            RuntimeError: If transcription fails after all retries.
        """
        # Split audio into chunks
        uid = os.path.splitext(os.path.basename(audio_path))[0]
        chunks_dir = os.path.join(os.path.dirname(audio_path), f"chunks_{uid}")
        chunk_paths = split_audio_ffmpeg(
            audio_path, chunks_dir, chunk_duration=self.chunk_duration
        )

        all_segments: List[Dict[str, Any]] = []
        offset = 0.0

        for i, chunk_path in enumerate(chunk_paths):
            segments = self._transcribe_chunk(chunk_path, i, len(chunk_paths))

            # Adjust timestamps by offset
            for seg in segments:
                all_segments.append(
                    {
                        "start": offset + seg["start"],
                        "end": offset + seg["end"],
                        "text": seg["text"],
                    }
                )

            offset += get_audio_duration(chunk_path)

        return {"segments": all_segments}

    def _transcribe_chunk(
        self, chunk_path: str, chunk_index: int, total_chunks: int
    ) -> List[Dict[str, Any]]:
        """
        Transcribe a single audio chunk with retry logic.

        Args:
            chunk_path: Path to the audio chunk.
            chunk_index: Index of this chunk (for logging).
            total_chunks: Total number of chunks (for logging).

        Returns:
            List of segment dicts with "start", "end", "text" keys.

        Raises:
            RuntimeError: If transcription fails after all retries.
        """
        url, headers, data = self._get_request_params()

        for attempt in range(self.max_retries):
            with open(chunk_path, "rb") as f:
                logger.info(
                    "%s uploading chunk %d/%d: %s",
                    self.provider_name,
                    chunk_index + 1,
                    total_chunks,
                    chunk_path,
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
                            "Rate limited (429). Retrying in %ds (attempt %d/%d)...",
                            wait,
                            attempt + 1,
                            self.max_retries,
                        )
                        time.sleep(wait)
                        continue

                    response.raise_for_status()
                    segments = response.json().get("segments", [])
                    logger.info(
                        "Transcribed chunk %d/%d: %d segments",
                        chunk_index + 1,
                        total_chunks,
                        len(segments),
                    )
                    return segments

                except requests.RequestException as e:
                    logger.error(
                        "%s Whisper failed on chunk %s: %s",
                        self.provider_name,
                        chunk_path,
                        e,
                    )
                    if attempt == self.max_retries - 1:
                        raise RuntimeError(
                            f"{self.provider_name} Whisper failed after "
                            f"{self.max_retries} retries: {e}"
                        ) from e

                    wait = self._get_retry_wait_time(attempt)
                    logger.warning("Retrying in %ds...", wait)
                    time.sleep(wait)

        raise RuntimeError(
            f"{self.provider_name} Whisper too many retries for chunk {chunk_path}"
        )

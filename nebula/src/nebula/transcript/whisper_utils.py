import logging
import os
import time
from typing import Any

import ffmpeg  # type: ignore
import requests

from nebula.common.llm_config import load_llm_config
from nebula.transcript.audio_utils import split_audio_ffmpeg

logger = logging.getLogger(__name__)


def get_audio_duration(audio_path: str) -> float:
    """Get the duration of the audio file using ffmpeg."""
    probe = ffmpeg.probe(audio_path)
    return float(probe["format"]["duration"])


def transcribe_with_whisper(audio_path: str) -> dict:
    config = load_llm_config(model="whisper")
    llm_type = config.get("type")
    if llm_type not in ("azure_whisper", "openai_whisper"):
        raise ValueError(f"Unsupported Whisper LLM type: {llm_type}")
    return transcribe_audio_chunks(audio_path, config)


def _get_whisper_request_params(config: Any) -> tuple[str, dict, dict]:
    """Build provider-specific request parameters for Whisper API.

    Returns:
        tuple: (url, headers, data_payload)
    """
    llm_type = config.get("type")

    if llm_type == "azure_whisper":
        endpoint = config["endpoint"]
        api_version = config["api_version"]
        url = (
            f"{endpoint}/openai/deployments/whisper/audio/transcriptions"
            f"?api-version={api_version}"
        )
        headers = {"api-key": config["api_key"]}
        data = {
            "response_format": "verbose_json",
            "timestamp_granularities[]": "segment",
        }
    elif llm_type == "openai_whisper":
        url = "https://api.openai.com/v1/audio/transcriptions"
        api_key = config["api_key"]
        headers = {"Authorization": f"Bearer {api_key}"}
        data = {
            "model": config["model"],
            "response_format": "verbose_json",
            "timestamp_granularities[]": "segment",
        }
    else:
        raise ValueError(f"Unsupported Whisper type: {llm_type}")

    return url, headers, data


def _get_retry_wait_time(config: Any, attempt: int) -> int:
    """Get provider-specific retry wait time for rate limiting."""
    llm_type = config.get("type")
    if llm_type == "azure_whisper":
        return 30 * (attempt + 1)
    if llm_type == "openai_whisper":
        return 10 * (attempt + 1)
    return 30 * (attempt + 1)  # Default fallback


def transcribe_audio_chunks(audio_path: str, config: Any) -> dict:
    """Unified transcription logic for both Azure and OpenAI Whisper."""
    provider_name = config.get("type", "Unknown").replace("_whisper", "").title()

    uid = os.path.splitext(os.path.basename(audio_path))[0]
    chunks_dir = os.path.join(os.path.dirname(audio_path), f"chunks_{uid}")
    chunk_paths = split_audio_ffmpeg(audio_path, chunks_dir, chunk_duration=900)

    all_segments = []
    offset = 0.0
    max_retries = 6

    for i, chunk_path in enumerate(chunk_paths):
        success = False
        for attempt in range(max_retries):
            with open(chunk_path, "rb") as f:
                logger.info(
                    "%s uploading chunk %s/%s: %s",
                    provider_name,
                    i + 1,
                    len(chunk_paths),
                    chunk_path,
                )
                try:
                    url, headers, data = _get_whisper_request_params(config)

                    response = requests.post(
                        url=url,
                        headers=headers,
                        files={"file": (os.path.basename(chunk_path), f, "audio/mp3")},
                        data=data,
                        timeout=60,
                    )

                    if response.status_code == 429:
                        wait = _get_retry_wait_time(config, attempt)
                        logger.warning(
                            "429 Too Many Requests. Retrying in %ss...", wait
                        )
                        time.sleep(wait)
                        continue

                    response.raise_for_status()
                    segment_data = response.json().get("segments", [])
                    for seg in segment_data:
                        all_segments.append(
                            {
                                "start": offset + seg["start"],
                                "end": offset + seg["end"],
                                "text": seg["text"],
                            }
                        )
                    success = True
                    break

                except requests.RequestException as e:
                    logger.exception(
                        "%s Whisper failed on chunk %s: %s",
                        provider_name,
                        chunk_path,
                        e,
                    )

        if not success:
            raise RuntimeError(
                f"{provider_name} Whisper too many retries for chunk {chunk_path}"
            )

        offset += get_audio_duration(chunk_path)

    return {"segments": all_segments}

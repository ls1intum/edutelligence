import logging
import os
import time

import ffmpeg  # type: ignore
import requests

from nebula.transcript.audio_utils import split_audio_ffmpeg
from nebula.transcript.config import Config
from nebula.transcript.llm_utils import load_llm_config

logger = logging.getLogger(__name__)


def get_audio_duration(audio_path: str) -> float:
    """Get the duration of the audio file using ffmpeg."""
    probe = ffmpeg.probe(audio_path)
    return float(probe["format"]["duration"])


def transcribe_with_azure_whisper(audio_path: str, llm_id: str | None = None) -> dict:
    llm_id = llm_id or Config.get_whisper_llm_id()
    config = load_llm_config(llm_id=llm_id)
    headers = {"api-key": config["api_key"]}

    uid = os.path.splitext(os.path.basename(audio_path))[0]
    chunks_dir = os.path.join(os.path.dirname(audio_path), f"chunks_{uid}")
    chunk_paths = split_audio_ffmpeg(audio_path, chunks_dir, chunk_duration=180)

    all_segments = []
    offset = 0.0
    max_retries = 6

    for i, chunk_path in enumerate(chunk_paths):
        success = False
        for attempt in range(max_retries):
            with open(chunk_path, "rb") as f:
                logger.info(
                    "Azure uploading chunk %s/%s: %s",
                    i + 1,
                    len(chunk_paths),
                    chunk_path,
                )
                try:
                    response = requests.post(
                        url=(
                            f'{config["endpoint"]}/openai/deployments/whisper/audio/transcriptions'
                            f'?api-version={config["api_version"]}'
                        ),
                        headers=headers,
                        files={"file": (os.path.basename(chunk_path), f, "audio/wav")},
                        data={
                            "response_format": "verbose_json",
                            "timestamp_granularities[]": "segment",
                        },
                        timeout=60,
                    )

                    if response.status_code == 429:
                        wait = 60 * (attempt + 1)
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
                    logger.error("Azure Whisper failed on chunk %s: %s", chunk_path, e)

        if not success:
            raise RuntimeError(f"Azure Whisper too many retries for chunk {chunk_path}")

        offset += get_audio_duration(chunk_path)

    return {"segments": all_segments}


def transcribe_with_openai_whisper(audio_path: str, llm_id: str | None = None) -> dict:
    llm_id = llm_id or Config.get_whisper_llm_id()
    config = load_llm_config(llm_id=llm_id)
    headers = {"Authorization": f'Bearer {config["api_key"]}'}

    uid = os.path.splitext(os.path.basename(audio_path))[0]
    chunks_dir = os.path.join(os.path.dirname(audio_path), f"chunks_{uid}")
    chunk_paths = split_audio_ffmpeg(audio_path, chunks_dir, chunk_duration=180)

    all_segments = []
    offset = 0.0
    max_retries = 6

    for i, chunk_path in enumerate(chunk_paths):
        success = False
        for attempt in range(max_retries):
            with open(chunk_path, "rb") as f:
                logger.info(
                    "OpenAI uploading chunk %s/%s: %s",
                    i + 1,
                    len(chunk_paths),
                    chunk_path,
                )
                try:
                    response = requests.post(
                        url="https://api.openai.com/v1/audio/transcriptions",
                        headers=headers,
                        files={"file": (os.path.basename(chunk_path), f, "audio/wav")},
                        data={
                            "model": config["model"],
                            "response_format": "verbose_json",
                            "timestamp_granularities[]": "segment",
                        },
                        timeout=60,
                    )

                    if response.status_code == 429:
                        wait = 10 * (attempt + 1)
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
                    logger.error("OpenAI Whisper failed on chunk %s: %s", chunk_path, e)

        if not success:
            raise RuntimeError(
                f"OpenAI Whisper too many retries for chunk {chunk_path}"
            )

        offset += get_audio_duration(chunk_path)

    return {"segments": all_segments}

import os
import logging
import requests
import ffmpeg

from nebula.transcript.audio_utils import split_audio_ffmpeg
from nebula.transcript.llm_utils import load_llm_config


def get_audio_duration(audio_path: str) -> float:
    """Use ffmpeg to get the duration of an audio file in seconds."""
    probe = ffmpeg.probe(audio_path)
    return float(probe['format']['duration'])


def transcribe_with_azure_whisper(audio_path: str, llm_id="azure-whisper"):
    config = load_llm_config(llm_id=llm_id)
    headers = {
        "api-key": config["api_key"]
    }

    uid = os.path.splitext(os.path.basename(audio_path))[0]
    chunks_dir = os.path.join(os.path.dirname(audio_path), f"chunks_{uid}")
    chunk_paths = split_audio_ffmpeg(audio_path, chunks_dir, chunk_duration=60)

    all_segments = []
    offset = 0.0  # running timestamp in seconds

    for chunk_path in chunk_paths:
        with open(chunk_path, "rb") as f:
            logging.info(f"Sending chunk to Azure Whisper: {chunk_path}")
            response = requests.post(
                f"{config['endpoint']}/openai/deployments/whisper/audio/transcriptions?api-version={config['api_version']}",
                headers=headers,
                files={"file": (os.path.basename(chunk_path), f, "audio/wav")},
                data={
                    "response_format": "verbose_json",
                    "timestamp_granularities[]": "segment"
                }
            )
            response.raise_for_status()
            segment_data = response.json().get("segments", [])

            for seg in segment_data:
                all_segments.append({
                    "start": offset + seg["start"],
                    "end": offset + seg["end"],
                    "text": seg["text"]
                })

        offset += get_audio_duration(chunk_path)

    return {"segments": all_segments}

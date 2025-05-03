import logging
import whisper
from config import Config

try:
    import torch
except ImportError:
    raise ImportError("Torch is required by Whisper but not installed.")

logging.basicConfig(level=getattr(logging, Config.LOG_LEVEL))
logging.info("Loading Whisper model...")

_model = whisper.load_model(Config.WHISPER_MODEL)

if torch.cuda.is_available():
    logging.info("Moving Whisper model to GPU.")
    _model = _model.to("cuda")
else:
    logging.info("Using Whisper model on CPU.")


def transcribe_with_local_whisper(audio_path: str) -> dict:
    """Transcribe an audio file using the local Whisper model."""
    logging.info(f"Transcribing {audio_path} ...")
    return _model.transcribe(audio_path)

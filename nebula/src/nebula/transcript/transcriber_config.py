"""Transcriber-specific configuration."""

from nebula.common.config import Config

# Video storage path for transcription service
VIDEO_STORAGE_PATH = Config.BASE_DIR.parent / "temp"


def ensure_dirs() -> None:
    """Ensure necessary directories exist for transcription service."""
    VIDEO_STORAGE_PATH.mkdir(parents=True, exist_ok=True)

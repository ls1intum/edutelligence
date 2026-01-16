"""Transcriber-specific configuration."""

from pathlib import Path

from nebula.common.config import get_required_env

# Video/audio storage path - must be explicitly configured via environment
VIDEO_STORAGE_PATH = Path(get_required_env("NEBULA_TEMP_DIR"))


def ensure_dirs() -> None:
    """Ensure necessary directories exist for transcription service."""
    VIDEO_STORAGE_PATH.mkdir(parents=True, exist_ok=True)

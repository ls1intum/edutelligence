"""
Configuration for the video storage service
"""

import os
from pathlib import Path


class Config:
    """Configuration for video storage service"""

    # Storage paths
    STORAGE_DIR = os.getenv("VIDEO_STORAGE_DIR", "/app/video_storage")
    TEMP_DIR = os.getenv("TEMP_DIR", "/app/temp")

    # File size limits
    MAX_FILE_SIZE = int(
        os.getenv("MAX_VIDEO_SIZE", 5 * 1024 * 1024 * 1024)
    )  # 5GB default
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", 1024 * 1024))  # 1MB chunks

    # Allowed video formats
    ALLOWED_EXTENSIONS = {
        ".mp4",
        ".avi",
        ".mov",
        ".mkv",
        ".webm",
        ".flv",
        ".wmv",
    }
    ALLOWED_MIME_TYPES = {
        "video/mp4",
        "video/x-msvideo",
        "video/quicktime",
        "video/x-matroska",
        "video/webm",
        "video/x-flv",
        "video/x-ms-wmv",
    }

    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    @staticmethod
    def ensure_dirs():
        """Create necessary directories if they don't exist"""
        Path(Config.STORAGE_DIR).mkdir(parents=True, exist_ok=True)
        Path(Config.TEMP_DIR).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def get_log_level():
        """Get log level from config"""
        return Config.LOG_LEVEL

    @staticmethod
    def get_storage_path(video_id: str) -> Path:
        """Get the full storage path for a video"""
        return Path(Config.STORAGE_DIR) / video_id

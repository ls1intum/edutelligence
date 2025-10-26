"""
Storage service for managing video files
"""

import json
import logging
import shutil
import subprocess  # nosec B404
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from nebula.video_storage.config import Config
from nebula.video_storage.dto import VideoMetadata

logger = logging.getLogger(__name__)


class VideoStorageService:
    """Service for storing and retrieving videos"""

    METADATA_FILENAME = "metadata.json"

    def __init__(self):
        self.storage_dir = Path(Config.STORAGE_DIR)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def generate_video_id(self) -> str:
        """Generate a unique video ID"""
        return str(uuid.uuid4())

    def save_video(
        self,
        video_data: bytes,
        filename: str,
        content_type: str,
        video_id: Optional[str] = None,
    ) -> VideoMetadata:
        """
        Save video to storage and convert to HLS format

        Args:
            video_data: Binary video data
            filename: Original filename
            content_type: MIME type
            video_id: Optional video ID (generated if not provided)

        Returns:
            VideoMetadata with storage information
        """
        if video_id is None:
            video_id = self.generate_video_id()

        # Create directory for this video
        video_dir = self.storage_dir / video_id
        video_dir.mkdir(parents=True, exist_ok=True)

        # Save original video file
        video_path = video_dir / filename
        with open(video_path, "wb") as f:
            f.write(video_data)

        # Convert to HLS format
        try:
            duration = self._convert_to_hls(video_dir, video_path)
        except Exception as e:
            logger.error("Error converting video to HLS: %s", e)
            # Clean up and re-raise
            self.delete_video(video_id)
            raise

        # Create metadata
        metadata = VideoMetadata(
            video_id=video_id,
            filename=filename,
            content_type=content_type,
            size_bytes=len(video_data),
            uploaded_at=datetime.now(),
            duration_seconds=duration,
        )

        # Save metadata
        self._save_metadata(video_id, metadata)

        logger.info(
            "Saved video %s (%s) - %s bytes, converted to HLS",
            video_id,
            filename,
            len(video_data),
        )
        return metadata

    def _convert_to_hls(self, video_dir: Path, video_path: Path) -> Optional[float]:
        """
        Convert video to HLS format using FFmpeg

        Args:
            video_dir: Directory to store HLS files
            video_path: Path to original video file

        Returns:
            Video duration in seconds, or None if not available
        """
        hls_dir = video_dir / "hls"
        hls_dir.mkdir(exist_ok=True)

        playlist_path = hls_dir / "playlist.m3u8"
        segment_pattern = hls_dir / "segment%03d.ts"

        logger.info("Converting video to HLS: %s", video_path)

        try:
            # FFmpeg command to convert to HLS
            # - segment_time: 10 seconds per segment
            # - hls_list_size: 0 means include all segments
            # - hls_flags: single_file creates one playlist for entire video
            cmd = [
                "ffmpeg",
                "-i",
                str(video_path),
                "-c:v",
                "libx264",  # H.264 video codec
                "-c:a",
                "aac",  # AAC audio codec
                "-b:v",
                "2M",  # Video bitrate
                "-b:a",
                "128k",  # Audio bitrate
                "-f",
                "hls",
                "-hls_time",
                "10",  # 10 second segments
                "-hls_list_size",
                "0",  # Include all segments
                "-hls_segment_filename",
                str(segment_pattern),
                str(playlist_path),
                "-y",  # Overwrite output files
            ]

            # Run FFmpeg
            subprocess.run(  # nosec B603
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=3600,  # 1 hour timeout
            )

            logger.info("HLS conversion successful: %s", playlist_path)

            # Get video duration
            duration = self._get_video_duration(video_path)
            return duration

        except subprocess.CalledProcessError as e:
            logger.error("FFmpeg error: %s", e.stderr)
            raise RuntimeError(f"Failed to convert video to HLS: {e.stderr}") from e
        except subprocess.TimeoutExpired as exc:
            logger.error("FFmpeg timeout")
            raise RuntimeError("Video conversion timed out") from exc
        except Exception as e:
            logger.error("Unexpected error during HLS conversion: %s", e)
            raise

    def _get_video_duration(self, video_path: Path) -> Optional[float]:
        """
        Get video duration using FFprobe

        Args:
            video_path: Path to video file

        Returns:
            Duration in seconds, or None if not available
        """
        try:
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ]

            result = subprocess.run(  # nosec B603
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )

            duration = float(result.stdout.strip())
            return duration

        except (
            subprocess.CalledProcessError,
            ValueError,
            subprocess.TimeoutExpired,
        ) as e:
            logger.warning("Could not get video duration: %s", e)
            return None

    def get_video_path(self, video_id: str) -> Optional[Path]:
        """Get the path to a video file"""
        video_dir = self.storage_dir / video_id
        if not video_dir.exists():
            return None

        # Find the video file in the directory
        metadata = self.get_metadata(video_id)
        if metadata is None:
            return None

        video_path = video_dir / metadata.filename
        if video_path.exists():
            return video_path
        return None

    def get_playlist_path(self, video_id: str) -> Optional[Path]:
        """Get the path to the HLS playlist file"""
        video_dir = self.storage_dir / video_id
        playlist_path = video_dir / "hls" / "playlist.m3u8"

        if playlist_path.exists():
            return playlist_path
        return None

    def get_hls_segment_path(self, video_id: str, segment_name: str) -> Optional[Path]:
        """Get the path to an HLS segment file"""
        video_dir = self.storage_dir / video_id
        segment_path = video_dir / "hls" / segment_name

        if segment_path.exists() and segment_name.endswith(".ts"):
            return segment_path
        return None

    def get_metadata(self, video_id: str) -> Optional[VideoMetadata]:
        """Get metadata for a video"""
        metadata_path = self.storage_dir / video_id / self.METADATA_FILENAME
        if not metadata_path.exists():
            return None

        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return VideoMetadata(**data)
        except Exception as e:
            logger.error("Error reading metadata for %s: %s", video_id, e)
            return None

    def _save_metadata(self, video_id: str, metadata: VideoMetadata):
        """Save metadata to disk"""
        metadata_path = self.storage_dir / video_id / self.METADATA_FILENAME
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata.model_dump(mode="json"), f, indent=2, default=str)

    def list_videos(self) -> List[VideoMetadata]:
        """List all stored videos"""
        videos = []
        for video_dir in self.storage_dir.iterdir():
            if video_dir.is_dir():
                metadata = self.get_metadata(video_dir.name)
                if metadata:
                    videos.append(metadata)

        # Sort by upload time (newest first)
        videos.sort(key=lambda x: x.uploaded_at, reverse=True)
        return videos

    def delete_video(self, video_id: str) -> bool:
        """
        Delete a video and its metadata (including HLS files)

        Returns:
            True if video was deleted, False if not found
        """
        video_dir = self.storage_dir / video_id
        if not video_dir.exists():
            return False

        try:
            # Delete all files recursively (including HLS directory)
            shutil.rmtree(video_dir)
            logger.info("Deleted video %s and all HLS files", video_id)
            return True
        except Exception as e:
            logger.error("Error deleting video %s: %s", video_id, e)
            return False

    def video_exists(self, video_id: str) -> bool:
        """Check if a video exists"""
        return self.get_video_path(video_id) is not None

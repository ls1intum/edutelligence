"""YouTube audio download utilities using yt-dlp."""

import os

import yt_dlp

from iris.common.logging_config import get_logger
from iris.tracing import observe

logger = get_logger(__name__)

MAX_VIDEO_DURATION_SECONDS = 6 * 60 * 60  # 6 hours


class YouTubeDownloadError(Exception):
    """Raised when a YouTube audio download fails."""


def _validate_youtube_video(video_url: str) -> dict:
    """
    Extract video metadata without downloading.
    Validates accessibility and duration.

    Returns:
        Dict with "id" and "duration" keys.

    Raises:
        YouTubeDownloadError: If video is private, unavailable, a live stream,
                              or exceeds the maximum duration.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        if "Private video" in error_msg or "Sign in" in error_msg:
            raise YouTubeDownloadError(
                "Video is private. Only public and unlisted YouTube videos "
                "can be transcribed."
            ) from e
        if "not available" in error_msg:
            raise YouTubeDownloadError(
                "Video is not available. It may have been deleted or is "
                "restricted in this region."
            ) from e
        raise YouTubeDownloadError(
            f"Failed to access YouTube video: {error_msg}"
        ) from e

    duration = info.get("duration")
    if not duration or duration <= 0:
        raise YouTubeDownloadError(
            "Cannot determine video duration. "
            "Live streams and premieres are not supported."
        )
    if duration > MAX_VIDEO_DURATION_SECONDS:
        raise YouTubeDownloadError(
            f"Video duration ({duration}s) exceeds maximum "
            f"({MAX_VIDEO_DURATION_SECONDS}s)."
        )

    return {"id": info.get("id", "unknown"), "duration": duration}


@observe(name="Download YouTube Audio")
def download_youtube_audio(
    video_url: str,
    audio_path: str,
    lecture_unit_id: int | None = None,
    timeout: int = 3600,
) -> None:
    """
    Download the audio track from a YouTube video.

    Uses yt-dlp to select the best audio stream and FFmpeg to convert
    to MP3 (matching the format produced by extract_audio in video_utils.py).

    Args:
        video_url: YouTube video URL (public or unlisted).
        audio_path: Full file path to save the audio (e.g., /tmp/uuid.mp3).
        lecture_unit_id: For log prefixing.
        timeout: Socket timeout in seconds for individual network operations.

    Raises:
        RuntimeError: If validation or download fails, consistent with
                      the video_utils error interface.
    """
    prefix = (
        f"[Lecture {lecture_unit_id}]"
        if lecture_unit_id is not None
        else "[Lecture ?]"
    )

    # Validate before downloading
    try:
        info = _validate_youtube_video(video_url)
    except YouTubeDownloadError as e:
        raise RuntimeError(str(e)) from e

    video_id = info["id"]
    duration = info["duration"]
    logger.info(
        "%s YouTube video validated: id=%s, duration=%ss",
        prefix,
        video_id,
        duration,
    )

    output_dir = os.path.dirname(audio_path)
    # Use the audio_path basename as output template to avoid filename
    # collisions when multiple downloads target the same temp directory
    basename = os.path.splitext(os.path.basename(audio_path))[0]
    output_template = os.path.join(output_dir, f"{basename}.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "0",  # Best quality
            }
        ],
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": timeout,
        "retries": 3,
        "fragment_retries": 3,
    }

    try:
        logger.info("%s Downloading YouTube audio...", prefix)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
    except yt_dlp.utils.DownloadError as e:
        raise RuntimeError(f"Failed to download YouTube audio: {e}") from e

    # yt-dlp writes to {basename}.mp3 which should match audio_path
    if not os.path.exists(audio_path):
        raise RuntimeError(
            f"YouTube audio file not found after download: {audio_path}"
        )

    file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    logger.info(
        "%s YouTube audio downloaded: %s (%.1f MB)",
        prefix,
        audio_path,
        file_size_mb,
    )

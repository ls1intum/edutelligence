"""Video processing utilities using FFmpeg."""

import subprocess  # nosec B404

from iris.common.logging_config import get_logger
from iris.tracing import observe

logger = get_logger(__name__)


@observe(name="Download Video")
def download_video(video_url: str, video_path: str) -> None:
    """
    Download a video from a URL using FFmpeg.

    Supports HTTP/HTTPS URLs including HLS streams (m3u8).

    Args:
        video_url: URL of the video to download.
        video_path: Local file path to save the video.

    Raises:
        RuntimeError: If FFmpeg fails to download the video.
    """
    logger.info("Downloading video from %s", video_url)

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-protocol_whitelist",
        "file,http,https,tcp,tls",
        "-i",
        video_url,
        "-c",
        "copy",
        "-bsf:a",
        "aac_adtstoasc",
        "-y",
        video_path,
    ]

    try:
        result = subprocess.run(
            command,
            shell=False,
            capture_output=True,
            text=True,
            check=True,
        )  # nosec B603

        if result.stdout:
            logger.debug("ffmpeg stdout: %s", result.stdout)
        if result.stderr:
            logger.debug("ffmpeg stderr: %s", result.stderr)

        logger.info("Video download complete: %s", video_path)

    except subprocess.CalledProcessError as e:
        logger.error("FFmpeg download failed: %s", e.stderr)
        raise RuntimeError(
            f"FFmpeg download failed with exit {e.returncode}: {e.stderr}"
        ) from e


@observe(name="Extract Audio")
def extract_audio(video_path: str, audio_path: str) -> None:
    """
    Extract audio from a video file using FFmpeg.

    Args:
        video_path: Path to the input video file.
        audio_path: Path to save the extracted audio file.

    Raises:
        RuntimeError: If FFmpeg fails to extract audio.
    """
    logger.info("Extracting audio from %s", video_path)

    command = [
        "ffmpeg",
        "-i",
        video_path,
        "-q:a",
        "0",  # Best quality audio
        "-map",
        "a",  # Audio stream only
        audio_path,
        "-y",
    ]

    try:
        subprocess.run(
            command,
            shell=False,
            capture_output=True,
            text=True,
            check=True,
        )  # nosec B603

        logger.info("Audio extraction complete: %s", audio_path)

    except subprocess.CalledProcessError as e:
        logger.error("FFmpeg audio extraction failed: %s", e.stderr)
        raise RuntimeError(f"FFmpeg audio extraction failed: {e.stderr}") from e

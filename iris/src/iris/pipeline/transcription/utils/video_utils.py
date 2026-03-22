"""Video processing utilities using FFmpeg."""

import subprocess  # nosec B404

from iris.common.logging_config import get_logger
from iris.tracing import observe

logger = get_logger(__name__)


def _log_prefix(lecture_unit_id: int | None) -> str:
    return (
        f"[Lecture {lecture_unit_id}]" if lecture_unit_id is not None else "[Lecture ?]"
    )


@observe(name="Download Video")
def download_video(
    video_url: str,
    video_path: str,
    lecture_unit_id: int | None = None,
    timeout: int = 3600,
) -> None:
    """
    Download a video from a URL using FFmpeg.

    Supports HTTP/HTTPS URLs including HLS streams (m3u8).

    Args:
        video_url: URL of the video to download.
        video_path: Local file path to save the video.
        lecture_unit_id: For log prefixing.
        timeout: Maximum seconds to wait for FFmpeg to complete (default: 3600).

    Raises:
        RuntimeError: If FFmpeg fails to download the video or the timeout is exceeded.
    """
    prefix = _log_prefix(lecture_unit_id)

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-protocol_whitelist",
        "http,https,tcp,tls",
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
        logger.info("%s Download in progress...", prefix)
        subprocess.run(  # nosec B603
            command,
            shell=False,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
        logger.info("%s Video download complete: %s", prefix, video_path)

    except subprocess.TimeoutExpired as e:
        logger.error("%s FFmpeg download timed out after %ds", prefix, timeout)
        raise RuntimeError(f"FFmpeg download timed out after {timeout}s") from e
    except subprocess.CalledProcessError as e:
        logger.error("FFmpeg download failed: %s", e.stderr)
        raise RuntimeError(
            f"FFmpeg download failed with exit {e.returncode}: {e.stderr}"
        ) from e


@observe(name="Extract Audio")
def extract_audio(
    video_path: str,
    audio_path: str,
    lecture_unit_id: int | None = None,
    timeout: int = 600,
) -> None:
    """
    Extract audio from a video file using FFmpeg.

    Args:
        video_path: Path to the input video file.
        audio_path: Path to save the extracted audio file.
        lecture_unit_id: For log prefixing.
        timeout: Maximum seconds to wait for FFmpeg to complete (default: 600).

    Raises:
        RuntimeError: If FFmpeg fails to extract audio or the timeout is exceeded.
    """
    prefix = _log_prefix(lecture_unit_id)
    logger.info("%s Extracting audio from %s", prefix, video_path)

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
            timeout=timeout,
        )  # nosec B603

        logger.info("%s Audio extraction complete: %s", prefix, audio_path)

    except subprocess.TimeoutExpired as e:
        logger.error("%s FFmpeg audio extraction timed out after %ds", prefix, timeout)
        raise RuntimeError(f"FFmpeg audio extraction timed out after {timeout}s") from e
    except subprocess.CalledProcessError as e:
        logger.error("%s FFmpeg audio extraction failed: %s", prefix, e.stderr)
        raise RuntimeError(f"FFmpeg audio extraction failed: {e.stderr}") from e

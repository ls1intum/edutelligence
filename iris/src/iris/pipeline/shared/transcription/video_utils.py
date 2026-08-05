import subprocess  # nosec B404
from typing import Optional

from iris.common.logging_config import get_logger
from iris.tracing import observe

logger = get_logger(__name__)


def _prefix(lecture_unit_id: Optional[int]) -> str:
    return (
        f"[Lecture {lecture_unit_id}]" if lecture_unit_id is not None else "[Lecture ?]"
    )


@observe(name="Download Video")
def download_video(
    video_url: str,
    video_path: str,
    timeout: int,
    lecture_unit_id: Optional[int] = None,
) -> None:
    """Download a video from a URL to disk using FFmpeg.

    Args:
        video_url: HTTP/HTTPS URL of the video to download.
        video_path: Destination file path for the downloaded video.
        timeout: Maximum seconds to wait before aborting (from config).
        lecture_unit_id: Used for log prefixing.

    Raises:
        RuntimeError: If FFmpeg exits with a non-zero return code.
    """
    prefix = _prefix(lecture_unit_id)
    logger.info("%s Downloading video from %s", prefix, video_url)

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
        raise RuntimeError(
            f"FFmpeg download timed out after {timeout}s for URL: {video_url}"
        ) from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"FFmpeg download failed (exit {e.returncode}): {e.stderr}"
        ) from e


@observe(name="Extract Audio")
def extract_audio(
    video_path: str,
    audio_path: str,
    timeout: int,
    lecture_unit_id: Optional[int] = None,
) -> None:
    """Extract the audio track from a video file using FFmpeg.

    Args:
        video_path: Path to the source video file.
        audio_path: Destination path for the extracted audio.
        timeout: Maximum seconds to wait before aborting (from config).
        lecture_unit_id: Used for log prefixing.

    Raises:
        RuntimeError: If FFmpeg exits with a non-zero return code.
    """
    prefix = _prefix(lecture_unit_id)
    logger.info("%s Extracting audio from %s", prefix, video_path)

    command = [
        "ffmpeg",
        "-i",
        video_path,
        "-q:a",
        "0",
        "-map",
        "a",
        audio_path,
        "-y",
    ]

    try:
        subprocess.run(  # nosec B603
            command,
            shell=False,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
        logger.info("%s Audio extraction complete: %s", prefix, audio_path)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"FFmpeg audio extraction timed out after {timeout}s") from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"FFmpeg audio extraction failed: {e.stderr}") from e

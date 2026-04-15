"""YouTube-specific helpers: validation and download via yt-dlp.

Surfaces failures via structured error codes that Pyris propagates to
Artemis in the status-update callback for instructor-visible messaging.
"""

import json
import re
import subprocess  # nosec B404
from typing import Any, Dict

from iris.common.logging_config import get_logger

logger = get_logger(__name__)


class YouTubeDownloadError(Exception):
    """Raised when yt-dlp cannot validate or download a YouTube video.

    Carries a structured ``error_code`` (one of YOUTUBE_PRIVATE,
    YOUTUBE_LIVE, YOUTUBE_TOO_LONG, YOUTUBE_UNAVAILABLE,
    YOUTUBE_DOWNLOAD_FAILED) so that upstream callers can attach it
    to the status callback verbatim.
    """

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


# Timeout for `yt-dlp --dump-json`. Metadata fetch is fast; 30 s is generous.
_VALIDATE_TIMEOUT_SECONDS = 30

_PRIVATE_PATTERNS = (
    re.compile(r"private video", re.IGNORECASE),
    re.compile(r"sign in", re.IGNORECASE),
)
_UNAVAILABLE_PATTERNS = (
    re.compile(r"video unavailable", re.IGNORECASE),
    re.compile(r"removed", re.IGNORECASE),
    re.compile(r"age[- ]restricted", re.IGNORECASE),
    re.compile(r"not available in your country", re.IGNORECASE),
)


def _classify_yt_dlp_error(stderr: str) -> str:
    """Map yt-dlp stderr to one of our structured error codes."""
    if any(p.search(stderr) for p in _PRIVATE_PATTERNS):
        return "YOUTUBE_PRIVATE"
    if any(p.search(stderr) for p in _UNAVAILABLE_PATTERNS):
        return "YOUTUBE_UNAVAILABLE"
    # Default: DOWNLOAD_FAILED (retryable per spec lines 88-91).
    # An unrecognized stderr could be a transient network/yt-dlp issue;
    # UNAVAILABLE is terminal and would block instructor-initiated retries.
    return "YOUTUBE_DOWNLOAD_FAILED"


def validate_youtube_video(
    url: str, max_duration_seconds: int
) -> Dict[str, Any]:
    """Validate a YouTube URL by fetching metadata via ``yt-dlp --dump-json``.

    Performs no download; only network cost is the metadata fetch.

    Raises:
        YouTubeDownloadError: with a structured ``error_code`` on any failure.
    """
    command = ["yt-dlp", "--dump-json", "--no-warnings", url]
    try:
        result = subprocess.run(  # nosec B603
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=_VALIDATE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as e:
        raise YouTubeDownloadError(
            "YOUTUBE_DOWNLOAD_FAILED",
            f"yt-dlp metadata fetch timed out after "
            f"{_VALIDATE_TIMEOUT_SECONDS}s for {url}",
        ) from e
    except subprocess.CalledProcessError as e:
        stderr = e.stderr or ""
        code = _classify_yt_dlp_error(stderr)
        raise YouTubeDownloadError(
            code,
            f"yt-dlp failed to validate {url}: {stderr.strip()}",
        ) from e
    except FileNotFoundError as e:
        # yt-dlp binary not installed — treat as download failure
        raise YouTubeDownloadError(
            "YOUTUBE_DOWNLOAD_FAILED", "yt-dlp binary not found on PATH"
        ) from e

    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise YouTubeDownloadError(
            "YOUTUBE_DOWNLOAD_FAILED",
            f"yt-dlp returned non-JSON output for {url}",
        ) from e

    if metadata.get("is_live"):
        raise YouTubeDownloadError(
            "YOUTUBE_LIVE", "Live streams cannot be transcribed"
        )
    duration = metadata.get("duration")
    if duration is not None and duration > max_duration_seconds:
        raise YouTubeDownloadError(
            "YOUTUBE_TOO_LONG",
            f"Video duration {duration}s exceeds max {max_duration_seconds}s",
        )
    return metadata

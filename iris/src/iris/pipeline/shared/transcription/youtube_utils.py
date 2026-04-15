"""YouTube-specific helpers: validation and download via yt-dlp.

Surfaces failures via structured error codes that Pyris propagates to
Artemis in the status-update callback for instructor-visible messaging.
"""


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

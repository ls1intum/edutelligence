import pytest

from iris.pipeline.shared.transcription.youtube_utils import (
    YouTubeDownloadError,
)


def test_error_carries_structured_code_and_message():
    err = YouTubeDownloadError("YOUTUBE_PRIVATE", "video is private")
    assert err.error_code == "YOUTUBE_PRIVATE"
    assert str(err) == "video is private"


def test_error_is_raisable():
    with pytest.raises(YouTubeDownloadError) as excinfo:
        raise YouTubeDownloadError("YOUTUBE_LIVE", "live stream not supported")
    assert excinfo.value.error_code == "YOUTUBE_LIVE"

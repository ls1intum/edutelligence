import json
import subprocess
from unittest.mock import patch

import pytest

from iris.pipeline.shared.transcription.youtube_utils import (
    YouTubeDownloadError,
    download_youtube_video,
    validate_youtube_video,
)


def test_error_carries_structured_code_and_message():
    err = YouTubeDownloadError("YOUTUBE_PRIVATE", "video is private")
    assert err.error_code == "YOUTUBE_PRIVATE"
    assert str(err) == "video is private"


def test_error_is_raisable():
    with pytest.raises(YouTubeDownloadError) as excinfo:
        raise YouTubeDownloadError("YOUTUBE_LIVE", "live stream not supported")
    assert excinfo.value.error_code == "YOUTUBE_LIVE"


def _metadata_json(**overrides) -> str:
    base = {
        "id": "dQw4w9WgXcQ",
        "title": "Test Video",
        "duration": 120,
        "is_live": False,
        "availability": "public",
        "formats": [],
    }
    base.update(overrides)
    return json.dumps(base)


def _mock_run_ok(metadata_json: str):
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=metadata_json, stderr=""
    )
    return patch("subprocess.run", return_value=completed)


def _mock_run_fail(stderr: str, returncode: int = 1):
    err = subprocess.CalledProcessError(
        returncode=returncode, cmd=["yt-dlp"], stderr=stderr
    )
    return patch("subprocess.run", side_effect=err)


def test_valid_video_returns_metadata():
    with _mock_run_ok(_metadata_json()):
        meta = validate_youtube_video(
            "https://youtu.be/dQw4w9WgXcQ", max_duration_seconds=3600
        )
    assert meta["id"] == "dQw4w9WgXcQ"
    assert meta["duration"] == 120


def test_live_stream_rejected():
    with _mock_run_ok(_metadata_json(is_live=True)):
        with pytest.raises(YouTubeDownloadError) as excinfo:
            validate_youtube_video(
                "https://youtu.be/X", max_duration_seconds=3600
            )
    assert excinfo.value.error_code == "YOUTUBE_LIVE"


def test_too_long_rejected():
    with _mock_run_ok(_metadata_json(duration=10000)):
        with pytest.raises(YouTubeDownloadError) as excinfo:
            validate_youtube_video(
                "https://youtu.be/X", max_duration_seconds=3600
            )
    assert excinfo.value.error_code == "YOUTUBE_TOO_LONG"


def test_private_video_rejected():
    # yt-dlp marks private videos with a specific stderr pattern
    private_stderr = (
        "ERROR: [youtube] X: Private video. "
        "Sign in if you've been granted access to this video"
    )
    with _mock_run_fail(private_stderr):
        with pytest.raises(YouTubeDownloadError) as excinfo:
            validate_youtube_video(
                "https://youtu.be/X", max_duration_seconds=3600
            )
    assert excinfo.value.error_code == "YOUTUBE_PRIVATE"


def test_unavailable_video_rejected():
    with _mock_run_fail("ERROR: [youtube] X: Video unavailable"):
        with pytest.raises(YouTubeDownloadError) as excinfo:
            validate_youtube_video(
                "https://youtu.be/X", max_duration_seconds=3600
            )
    assert excinfo.value.error_code == "YOUTUBE_UNAVAILABLE"


def test_unknown_yt_dlp_error_treated_as_download_failed():
    # Novel stderr pattern — default to DOWNLOAD_FAILED (retryable per spec
    # lines 88-91), NOT UNAVAILABLE. An unknown stderr could be transient
    # (network, yt-dlp bug); terminalizing it as UNAVAILABLE would forbid
    # retries forever.
    with _mock_run_fail("ERROR: some new yt-dlp error text"):
        with pytest.raises(YouTubeDownloadError) as excinfo:
            validate_youtube_video(
                "https://youtu.be/X", max_duration_seconds=3600
            )
    assert excinfo.value.error_code == "YOUTUBE_DOWNLOAD_FAILED"


def test_timeout_raises_download_failed():
    timeout_err = subprocess.TimeoutExpired(cmd=["yt-dlp"], timeout=30)
    with patch("subprocess.run", side_effect=timeout_err):
        with pytest.raises(YouTubeDownloadError) as excinfo:
            validate_youtube_video(
                "https://youtu.be/X", max_duration_seconds=3600
            )
    assert excinfo.value.error_code == "YOUTUBE_DOWNLOAD_FAILED"


def test_download_success_returns_output_path(tmp_path, monkeypatch):
    output = tmp_path / "video.mp4"

    def _fake_run(*args, **_):
        output.write_bytes(b"\x00")
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr("subprocess.run", _fake_run)
    result = download_youtube_video(
        "https://youtu.be/X", output, timeout=600
    )
    assert result == output
    assert output.exists()


def test_download_timeout_raises_download_failed(tmp_path, monkeypatch):
    timeout_err = subprocess.TimeoutExpired(cmd=["yt-dlp"], timeout=1)
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: (_ for _ in ()).throw(timeout_err),
    )
    with pytest.raises(YouTubeDownloadError) as excinfo:
        download_youtube_video(
            "https://youtu.be/X", tmp_path / "out.mp4", timeout=1
        )
    assert excinfo.value.error_code == "YOUTUBE_DOWNLOAD_FAILED"


def test_download_nonzero_exit_raises_download_failed(tmp_path, monkeypatch):
    err = subprocess.CalledProcessError(
        returncode=1, cmd=["yt-dlp"], stderr="network error"
    )
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: (_ for _ in ()).throw(err),
    )
    with pytest.raises(YouTubeDownloadError) as excinfo:
        download_youtube_video(
            "https://youtu.be/X", tmp_path / "out.mp4", timeout=600
        )
    assert excinfo.value.error_code == "YOUTUBE_DOWNLOAD_FAILED"


def test_download_output_missing_raises_download_failed(tmp_path, monkeypatch):
    # subprocess returns success but no file materialized — yt-dlp quirk
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: subprocess.CompletedProcess(
            args=a, returncode=0, stdout="", stderr=""
        ),
    )
    with pytest.raises(YouTubeDownloadError) as excinfo:
        download_youtube_video(
            "https://youtu.be/X", tmp_path / "missing.mp4", timeout=600
        )
    assert excinfo.value.error_code == "YOUTUBE_DOWNLOAD_FAILED"

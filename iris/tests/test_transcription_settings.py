from iris.config import TranscriptionSettings


def test_youtube_max_duration_default_is_six_hours():
    settings = TranscriptionSettings()
    assert settings.youtube_max_duration_seconds == 21600


def test_youtube_download_timeout_default_is_one_hour():
    # The default must be large enough to cover the slowest download up to
    # youtube_max_duration_seconds (6h). Operators can override via env.
    settings = TranscriptionSettings()
    assert settings.youtube_download_timeout_seconds == 3600

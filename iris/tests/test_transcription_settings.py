from iris.config import TranscriptionSettings


def test_youtube_max_duration_default_is_six_hours():
    settings = TranscriptionSettings()
    assert settings.youtube_max_duration_seconds == 21600


def test_youtube_download_timeout_default_is_ten_minutes():
    settings = TranscriptionSettings()
    assert settings.youtube_download_timeout_seconds == 600

import pytest
from pydantic import ValidationError

from iris.config import LectureIngestionSettings


def test_defaults_are_valid():
    settings = LectureIngestionSettings()
    assert settings.vision_max_attempts == 3
    assert settings.skip_check_fetch_limit == 10_000
    assert settings.convergence_max_escalations == 2
    assert settings.language_detection_min_chars == 200
    assert settings.language_detection_max_chars == 10_000
    assert settings.default_language == "en"


def test_vision_max_attempts_must_be_positive():
    # A non-positive value empties range(1, value + 1), so no vision request ever
    # runs and the pipeline fails with a misleading "None" underlying error.
    with pytest.raises(ValidationError):
        LectureIngestionSettings(vision_max_attempts=0)


def test_skip_check_fetch_limit_must_be_positive():
    # A non-positive value makes "len(chunks) >= limit" true after every fetch,
    # so the completeness check never sees a unit as complete and it re-ingests
    # on every run.
    with pytest.raises(ValidationError):
        LectureIngestionSettings(skip_check_fetch_limit=0)


def test_convergence_max_escalations_rejects_negative():
    with pytest.raises(ValidationError):
        LectureIngestionSettings(convergence_max_escalations=-1)


def test_convergence_max_escalations_allows_zero():
    # Zero is a legitimate way to disable escalation outright.
    settings = LectureIngestionSettings(convergence_max_escalations=0)
    assert settings.convergence_max_escalations == 0


def test_language_detection_min_chars_must_be_positive():
    with pytest.raises(ValidationError):
        LectureIngestionSettings(language_detection_min_chars=0)


def test_language_detection_max_chars_must_be_positive():
    with pytest.raises(ValidationError):
        LectureIngestionSettings(language_detection_max_chars=0)


def test_language_detection_max_must_be_at_least_min():
    with pytest.raises(ValidationError):
        LectureIngestionSettings(
            language_detection_min_chars=500, language_detection_max_chars=200
        )


def test_language_detection_max_equal_to_min_is_allowed():
    settings = LectureIngestionSettings(
        language_detection_min_chars=200, language_detection_max_chars=200
    )
    assert settings.language_detection_max_chars == 200

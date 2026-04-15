import pytest
from pydantic import ValidationError

from iris.domain.data.lecture_unit_page_dto import LectureUnitPageDTO
from iris.domain.data.video_source_type import VideoSourceType

_MINIMAL_PAYLOAD = {
    "lectureUnitId": 1,
    "lectureId": 2,
    "courseId": 3,
}


def test_defaults_to_tum_live_when_field_absent():
    dto = LectureUnitPageDTO(**_MINIMAL_PAYLOAD)
    assert dto.video_source_type == VideoSourceType.TUM_LIVE


def test_accepts_youtube_from_camelcase_alias():
    dto = LectureUnitPageDTO(**{**_MINIMAL_PAYLOAD, "videoSourceType": "YOUTUBE"})
    assert dto.video_source_type == VideoSourceType.YOUTUBE


def test_accepts_snake_case_field_name():
    dto = LectureUnitPageDTO(**{**_MINIMAL_PAYLOAD, "video_source_type": "YOUTUBE"})
    assert dto.video_source_type == VideoSourceType.YOUTUBE


def test_rejects_unknown_value():
    with pytest.raises(ValidationError):
        LectureUnitPageDTO(**{**_MINIMAL_PAYLOAD, "videoSourceType": "VIMEO"})

from pydantic import TypeAdapter

from iris.domain.data.lecture_context_dto import (
    CombinedViewContextDTO,
    LectureContextDTO,
    SlidesContextDTO,
    VideoContextDTO,
)

_adapter = TypeAdapter(LectureContextDTO)


def test_parses_standalone_slides_entry():
    dto = _adapter.validate_python({"type": "slides", "lectureUnitId": 123, "page": 5})
    assert isinstance(dto, SlidesContextDTO)
    assert dto.lecture_unit_id == 123
    assert dto.page == 5


def test_parses_standalone_video_entry():
    dto = _adapter.validate_python(
        {"type": "video", "lectureUnitId": 123, "timestamp": 45.2}
    )
    assert isinstance(dto, VideoContextDTO)
    assert dto.lecture_unit_id == 123
    assert dto.timestamp == 45.2


def test_parses_combined_view_with_both_nested():
    dto = _adapter.validate_python(
        {
            "type": "combinedView",
            "slides": {"type": "slides", "lectureUnitId": 123, "page": 5},
            "video": {"type": "video", "lectureUnitId": 123, "timestamp": 45.2},
        }
    )
    assert isinstance(dto, CombinedViewContextDTO)
    assert dto.slides is not None and dto.slides.page == 5
    assert dto.video is not None and dto.video.timestamp == 45.2
    assert dto.lecture_unit_id == 123


def test_combined_view_unit_id_prefers_slides():
    dto = CombinedViewContextDTO(
        type="combinedView",
        slides=SlidesContextDTO(type="slides", lectureUnitId=11, page=1),
        video=VideoContextDTO(type="video", lectureUnitId=22, timestamp=0.0),
    )
    assert dto.lecture_unit_id == 11


def test_combined_view_unit_id_falls_back_to_video():
    dto = _adapter.validate_python(
        {
            "type": "combinedView",
            "video": {"type": "video", "lectureUnitId": 77, "timestamp": 0.0},
        }
    )
    assert dto.slides is None
    assert dto.lecture_unit_id == 77


def test_combined_view_allows_slides_only():
    dto = _adapter.validate_python(
        {
            "type": "combinedView",
            "slides": {"type": "slides", "lectureUnitId": 9, "page": 3},
        }
    )
    assert dto.video is None
    assert dto.lecture_unit_id == 9

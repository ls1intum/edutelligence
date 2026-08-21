from iris.domain.data.lecture_dto import PyrisLectureDTO
from iris.domain.data.pyris_lecture_unit_dto import PyrisLectureUnitDTO
from iris.tools.lecture_list import create_tool_get_lecture_list


def _unit(unit_id, lecture_id, name):
    return PyrisLectureUnitDTO(
        lectureUnitId=unit_id, courseId=99, lectureId=lecture_id, name=name
    )


def test_lecture_list_tool_exposes_lecture_ids():
    lectures = [
        PyrisLectureDTO(
            id=42,
            title="Hashing",
            units=[_unit(1, 42, "Unit 1"), _unit(2, 42, "Unit 2")],
        ),
        PyrisLectureDTO(
            id=41, title="Sorting Algorithms", units=[_unit(3, 41, "Unit 1")]
        ),
    ]

    tool = create_tool_get_lecture_list(lectures, callback=None)

    assert tool() == [
        {
            "lecture_id": 42,
            "lecture_name": "Hashing",
            "lecture_unit_names": ["Unit 1", "Unit 2"],
        },
        {
            "lecture_id": 41,
            "lecture_name": "Sorting Algorithms",
            "lecture_unit_names": ["Unit 1"],
        },
    ]


def test_lecture_list_tool_lists_a_lecture_without_units():
    """A lecture whose units are all unreleased arrives with an empty units list."""
    tool = create_tool_get_lecture_list(
        [PyrisLectureDTO(id=42, title="Hashing")], callback=None
    )

    assert tool() == [
        {"lecture_id": 42, "lecture_name": "Hashing", "lecture_unit_names": []}
    ]


def test_lecture_list_tool_returns_empty_list_without_lectures():
    assert create_tool_get_lecture_list([], callback=None)() == []
    assert create_tool_get_lecture_list(None, callback=None)() == []

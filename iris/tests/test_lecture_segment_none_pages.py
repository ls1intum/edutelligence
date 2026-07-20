import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.retrieval.lecture.lecture_unit_segment_retrieval import (
    _coalesce_page_number,
)


def test_coalesce_prefers_display_page():
    assert _coalesce_page_number(4, 2) == 4


def test_coalesce_falls_back_to_page_number_on_none():
    assert _coalesce_page_number(None, 2) == 2


def test_coalesce_returns_sentinel_when_both_missing():
    assert _coalesce_page_number(None, None) == -1

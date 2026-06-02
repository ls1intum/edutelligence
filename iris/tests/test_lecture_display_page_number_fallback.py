from iris.retrieval.lecture.lecture_retrieval_utils import (
    resolve_display_page_number,
)


def test_missing_display_page_number_falls_back_to_page_number():
    properties = {"page_number": 7}

    display_page_number = resolve_display_page_number(
        properties, "display_page_number", "page_number"
    )

    assert display_page_number == 7


def test_explicit_unknown_display_page_number_is_preserved():
    properties = {"page_number": 7, "display_page_number": -1}

    display_page_number = resolve_display_page_number(
        properties, "display_page_number", "page_number"
    )

    assert display_page_number == -1

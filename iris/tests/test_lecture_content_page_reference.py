"""Tests for the page reference rendered into the lecture retrieval results.

Two numbers describe the same slide and the agent must not mix them up: the number printed on the
slide (what it may tell the student) and the slide's index in the deck (the point-out id, which the
point-out tool navigates by and which must never surface in an answer). Slides carrying no printed
number are stored with a -1 sentinel, which must not leak into the results as a page number.
"""

from iris.tools.lecture_content_retrieval import _format_page_reference


def test_printed_page_number_is_offered_alongside_the_point_out_id():
    assert _format_page_reference(8, 7) == "Page: 8 (point-out id: 7)"


def test_slide_without_a_printed_number_is_marked_unnumbered():
    # -1 is the ingestion sentinel for "no page number visible on the slide". Rendering it verbatim
    # would make the agent tell the student about "page -1".
    assert _format_page_reference(-1, 7) == "Page: unnumbered (point-out id: 7)"


def test_missing_printed_number_is_marked_unnumbered():
    assert _format_page_reference(None, 3) == "Page: unnumbered (point-out id: 3)"


def test_zero_is_treated_as_no_printed_number():
    assert _format_page_reference(0, 3) == "Page: unnumbered (point-out id: 3)"


def test_printed_number_may_differ_from_the_point_out_id():
    # The whole reason both numbers exist: a title page shifts the printed numbering against the
    # deck index, and only the index is valid for navigation.
    assert _format_page_reference(1, 2) == "Page: 1 (point-out id: 2)"

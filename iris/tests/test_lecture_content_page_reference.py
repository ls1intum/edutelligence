"""Tests for the page reference rendered into the lecture retrieval results.

Two numbers describe the same slide and the agent must not mix them up: the number printed on the
slide (what it may tell the student) and the slide's index in the deck (the point-out id, which the
point-out tool navigates by). Slides carrying no printed number are stored with a -1 sentinel, which
must not leak into the results as a page number.
"""

import pytest

from iris.tools.lecture_content_retrieval import _format_page_reference


@pytest.mark.parametrize(
    "display_page_number, page_number, expected",
    [
        # A title page shifts the printed numbering against the deck index; only the index navigates.
        (1, 2, "Page: 1, point-out id: 2"),
        # -1 is the ingestion sentinel for "no page number visible on the slide"; rendering it
        # verbatim would make the agent tell the student about "page -1".
        (-1, 7, "Page: unnumbered, point-out id: 7"),
        (0, 3, "Page: unnumbered, point-out id: 3"),
        (None, 3, "Page: unnumbered, point-out id: 3"),
    ],
)
def test_format_page_reference(display_page_number, page_number, expected):
    assert _format_page_reference(display_page_number, page_number) == expected

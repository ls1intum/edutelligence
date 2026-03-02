"""Tests for citation utilities."""

from iris.pipeline.shared.citation_utils import (
    build_faq_citation_id,
    build_lecture_citation_id,
)


def test_build_lecture_citation_id_basic():
    """Test building a basic lecture citation ID."""
    citation_id = build_lecture_citation_id(
        lecture_unit_id=123,
        page_number=5,
        citation_sequence_number=1,
    )
    assert citation_id == "[cite:L:123:5::!1]"


def test_build_lecture_citation_id_with_timestamps():
    """Test building a lecture citation ID with timestamps."""
    citation_id = build_lecture_citation_id(
        lecture_unit_id=123,
        page_number=5,
        start_time_sec=120,
        end_time_sec=180,
        citation_sequence_number=2,
    )
    assert citation_id == "[cite:L:123:5:120:180!2]"


def test_build_lecture_citation_id_no_page():
    """Test building a lecture citation ID without page number."""
    citation_id = build_lecture_citation_id(
        lecture_unit_id=456,
        citation_sequence_number=3,
    )
    assert citation_id == "[cite:L:456:::!3]"


def test_build_faq_citation_id():
    """Test building a FAQ citation ID."""
    citation_id = build_faq_citation_id(faq_id=789, citation_sequence_number=5)
    assert citation_id == "[cite:F:789:::!5]"


def test_build_faq_citation_id_various_ids():
    """Test building FAQ citation IDs with various IDs."""
    assert build_faq_citation_id(1, 1) == "[cite:F:1:::!1]"
    assert build_faq_citation_id(999, 10) == "[cite:F:999:::!10]"
    assert build_faq_citation_id(42, 100) == "[cite:F:42:::!100]"

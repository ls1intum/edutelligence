"""Tests for the deterministic quality verdict of ingested page chunks."""

from iris.pipeline.ingestion_quality import assess_page_chunks
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
)


def _chunk(page: int, text: str) -> dict:
    return {
        LectureUnitPageChunkSchema.PAGE_NUMBER.value: page,
        LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value: text,
    }


_GOOD_TEXT = (
    "This slide explains the gradient descent update rule and its learning "
    "rate trade-offs in detail, with a worked example over a convex loss."
)


def test_all_substantial_pages_score_one():
    score, flags = assess_page_chunks([_chunk(1, _GOOD_TEXT), _chunk(2, _GOOD_TEXT)])

    assert score == 1.0
    assert not flags


def test_empty_thin_and_garbled_pages_are_flagged():
    chunks = [
        _chunk(1, _GOOD_TEXT),
        _chunk(2, "   "),
        _chunk(3, "short"),
        _chunk(4, "@# $% ^& *( )_ +| ~` ={ }[ ]; :' <> ,. ?/ " * 5),
    ]

    score, flags = assess_page_chunks(chunks)

    assert score == 0.25
    assert any("empty pages: [2]" in flag for flag in flags)
    assert any("thin pages: [3]" in flag for flag in flags)
    assert any("garbled pages: [4]" in flag for flag in flags)


def test_no_chunks_scores_zero():
    score, flags = assess_page_chunks([])

    assert score == 0.0
    assert flags == ["no chunks"]


def test_chunks_of_one_page_are_pooled_before_judging():
    # Two thin chunks that together hold substantial text must not flag the page.
    mid = len(_GOOD_TEXT) // 2
    half = _GOOD_TEXT[:mid]
    other_half = _GOOD_TEXT[mid:]

    score, flags = assess_page_chunks([_chunk(1, half), _chunk(1, other_half)])

    assert score == 1.0
    assert not flags


def test_verdict_is_deterministic():
    chunks = [_chunk(1, _GOOD_TEXT), _chunk(2, "short")]

    assert assess_page_chunks(chunks) == assess_page_chunks(chunks)

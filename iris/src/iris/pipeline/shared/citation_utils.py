"""Utilities for building citation IDs."""

from typing import Optional


def build_lecture_citation_id(
    lecture_unit_id: int,
    page_number: Optional[int] = None,
    start_time_sec: Optional[int] = None,
    end_time_sec: Optional[int] = None,
    citation_sequence_number: int = 1,
) -> str:
    """Build lecture citation ID: [cite:L:<lecture_unit_id>:<page>:<start>:<end>!<seq>]."""
    return (
        f"[cite:L:{lecture_unit_id}:"
        f"{'' if page_number is None else page_number}:"
        f"{'' if start_time_sec is None else start_time_sec}:"
        f"{'' if end_time_sec is None else end_time_sec}!{citation_sequence_number}]"
    )


def build_faq_citation_id(faq_id: int, citation_sequence_number: int) -> str:
    """Build FAQ citation ID: [cite:F:<faq_id>:::!<seq>]."""
    return f"[cite:F:{faq_id}:::!{citation_sequence_number}]"

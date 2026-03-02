"""Utilities for building citation IDs."""

from typing import Optional


def build_lecture_citation_id(
    lecture_unit_id: int,
    page_number: Optional[int] = None,
    start_time_sec: Optional[int] = None,
    end_time_sec: Optional[int] = None,
    citation_sequence_number: Optional[int] = None,
) -> str:
    """Build lecture citation ID: [cite:L:<lecture_unit_id>:<page>:<start>:<end>!<seq>]."""

    def fmt(val):
        return "" if val is None else str(val)

    return (
        f"[cite:L:{fmt(lecture_unit_id)}:{fmt(page_number)}:"
        f"{fmt(start_time_sec)}:{fmt(end_time_sec)}!{fmt(citation_sequence_number)}]"
    )


def build_faq_citation_id(faq_id: int, citation_sequence_number: int) -> str:
    """Build FAQ citation ID: [cite:F:<faq_id>:::!<seq>]."""
    return f"[cite:F:{faq_id}:::!{citation_sequence_number}]"

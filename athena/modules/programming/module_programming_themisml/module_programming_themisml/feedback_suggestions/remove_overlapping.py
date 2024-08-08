"""
Feedback suggestions can overlap each other, which is not ideal.
This module removes overlapping suggestions.
"""

from typing import List

from athena.programming import Feedback


def is_overlapping(feedback1: Feedback, feedback2: Feedback) -> bool:
    """Returns whether the two given feedbacks overlap."""
    if feedback1.file_path != feedback2.file_path:
        # feedback in different files
        return False
    if feedback1.line_start is None or feedback2.line_start is None or feedback1.line_end is None or feedback2.line_end is None:
        # unreferenced feedback (both start and end are None because of Schema validation for line_end)
        return False
    if feedback1.line_start > feedback2.line_end:
        return False
    if feedback2.line_start > feedback1.line_end:
        return False
    return True


def filter_overlapping_suggestions(suggestions: List[Feedback]) -> List[Feedback]:
    """Filters out overlapping suggestions we don't want to suggest to tutors.

    Arguments:
        suggestions {list} -- List of suggestions to filter
    """
    # sort suggestions by similarity_score to keep the most accurate ones
    suggestions.sort(key=lambda s: s.meta.get("similarity_score", 0), reverse=True)
    # skip suggestions if they overlap with a suggestion that was already added
    added_suggestions: List[Feedback] = []
    for suggestion in suggestions:
        if any(is_overlapping(suggestion, added_suggestion) for added_suggestion in added_suggestions):
            continue
        added_suggestions.append(suggestion)
    return added_suggestions

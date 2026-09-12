"""Unit tests for inline citation markers in global-search answers:
sanitation, renumbering after the used-sources filter, and their
integration with parse_answer_response's grounding guards."""

import json

from iris.pipeline.global_search_pipeline import (
    parse_answer_response,
    renumber_citation_markers,
    sanitize_citation_markers,
)


class TestSanitizeCitationMarkers:
    """Validation of raw model-emitted [n] markers."""

    def test_in_range_markers_are_kept_and_collected(self):
        answer, cited = sanitize_citation_markers("A claim.[1] Another.[3]", 3)
        assert answer == "A claim.[1] Another.[3]"
        assert cited == {0, 2}

    def test_out_of_range_markers_are_stripped(self):
        answer, cited = sanitize_citation_markers("Wrong.[9] Right.[2]", 3)
        assert answer == "Wrong. Right.[2]"
        assert cited == {1}

    def test_zero_marker_is_stripped(self):
        answer, cited = sanitize_citation_markers("Claim.[0]", 3)
        assert answer == "Claim."
        assert cited == set()

    def test_adjacent_duplicates_collapse(self):
        answer, cited = sanitize_citation_markers("Claim.[1][1][1]", 3)
        assert answer == "Claim.[1]"
        assert cited == {0}

    def test_duplicates_collapse_across_a_removed_invalid_marker(self):
        answer, cited = sanitize_citation_markers("Claim.[1][9][1]", 3)
        assert answer == "Claim.[1]"
        assert cited == {0}

    def test_distinct_chains_are_preserved(self):
        answer, cited = sanitize_citation_markers("Claim.[1][2][3]", 3)
        assert answer == "Claim.[1][2][3]"
        assert cited == {0, 1, 2}

    def test_repeat_after_text_is_kept(self):
        answer, cited = sanitize_citation_markers("A.[1] B.[1]", 3)
        assert answer == "A.[1] B.[1]"
        assert cited == {0}

    def test_answer_without_markers_passes_through(self):
        answer, cited = sanitize_citation_markers("Plain answer.", 3)
        assert answer == "Plain answer."
        assert cited == set()

    def test_none_answer_passes_through(self):
        answer, cited = sanitize_citation_markers(None, 3)
        assert answer is None
        assert cited == set()


class TestRenumberCitationMarkers:
    """Context numbering -> returned-sources numbering."""

    def test_renumbers_onto_the_filtered_list(self):
        # Context sources 2 and 4 were used -> returned positions 1 and 2.
        answer = renumber_citation_markers("A.[2] B.[4]", {2: 1, 4: 2})
        assert answer == "A.[1] B.[2]"

    def test_unknown_numbers_are_stripped_defensively(self):
        assert renumber_citation_markers("A.[7]", {2: 1}) == "A."

    def test_none_answer_passes_through(self):
        assert renumber_citation_markers(None, {1: 1}) is None


class TestParseIntegration:
    """Markers flow through parse_answer_response and count as grounding."""

    def test_markers_extend_used_sources(self):
        raw = json.dumps({"answer": "A.[1] B.[3]", "used_sources": [1]})
        answer, used = parse_answer_response(raw, 3)
        assert answer == "A.[1] B.[3]"
        assert used == {0, 2}

    def test_marker_only_attribution_is_not_suppressed_as_ungrounded(self):
        # The model cited inline but forgot used_sources: the ungrounded
        # guard must treat the markers as grounding.
        raw = json.dumps(
            {"answer": "The quiz is worth 4 points.[1]", "used_sources": []}
        )
        answer, used = parse_answer_response(raw, 2)
        assert answer == "The quiz is worth 4 points.[1]"
        assert used == {0}

    def test_hallucinated_markers_do_not_ground_an_answer(self):
        raw = json.dumps({"answer": "Yes.[9]", "used_sources": []})
        answer, used = parse_answer_response(raw, 2)
        assert answer is None  # marker stripped -> ungrounded -> suppressed
        assert used == set()

    def test_markerless_answers_behave_exactly_as_before(self):
        raw = json.dumps({"answer": "A plain answer.", "used_sources": [2]})
        answer, used = parse_answer_response(raw, 3)
        assert answer == "A plain answer."
        assert used == {1}

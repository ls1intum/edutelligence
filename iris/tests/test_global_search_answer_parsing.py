"""Unit tests for the global-search answer parsing/sanitizing pipeline.

Every case below reproduces a shape observed live on the test server during
the July 2026 investigation (see iris/docs/global-search/): the Used_sources
UI leak, dropped JSON envelopes, LaTeX-backslash JSON breakage, ungrounded
and refusal answers.
"""

from iris.pipeline.global_search_pipeline import parse_answer_response


def test_clean_json_answer():
    answer, used = parse_answer_response(
        '{"answer": "RL is...", "used_sources": [1, 3]}', 5
    )
    assert answer == "RL is..."
    assert used == {0, 2}


def test_used_sources_duplicated_inside_answer_is_stripped():
    # The exact UI-observed bug: valid JSON whose answer string ALSO ends
    # with a plain-text "Used_sources: [...]" line.
    answer, used = parse_answer_response(
        '{"answer": "RL is a paradigm.\\n\\nUsed_sources: [1, 3]",'
        ' "used_sources": [1, 3]}',
        5,
    )
    assert answer == "RL is a paradigm."
    assert used == {0, 2}


def test_plain_text_with_trailing_schema_line_recovers_attribution():
    answer, used = parse_answer_response(
        "Deep learning is a subfield.\n\nUsed_sources: [2]", 5
    )
    assert answer == "Deep learning is a subfield."
    assert used == {1}


def test_trailing_line_variant_casing_and_spacing():
    answer, used = parse_answer_response("Answer text here.\nused sources: [1,2].", 5)
    assert answer == "Answer text here."
    assert used == {0, 1}


def test_json_embedded_in_prose_is_salvaged():
    answer, used = parse_answer_response(
        'Here is my response: {"answer": "X", "used_sources": [1]} hope that helps', 5
    )
    assert answer == "X"
    assert used == {0}


def test_null_json_yields_no_answer():
    answer, used = parse_answer_response('{"answer": null, "used_sources": []}', 5)
    assert answer is None
    assert used == set()


def test_plain_text_without_schema_line_keeps_all_sources():
    answer, used = parse_answer_response(
        "Just some text answer without any structure at all, long enough not "
        "to look like a refusal and containing no schema imitation.",
        5,
    )
    assert answer is not None
    assert used == {0, 1, 2, 3, 4}


def test_latex_backslashes_are_repaired():
    answer, used = parse_answer_response(
        '{"answer": "mean $$\\mu$$ of values", "used_sources": [1]}', 5
    )
    assert answer == "mean $$\\mu$$ of values"
    assert used == {0}


def test_markdown_fenced_json():
    answer, used = parse_answer_response(
        '```json\n{"answer": "Y", "used_sources": [2]}\n```', 5
    )
    assert answer == "Y"
    assert used == {1}


def test_trailing_empty_index_line():
    answer, used = parse_answer_response(
        "No relevant content in this very long explanatory answer about the "
        "topic that easily exceeds the refusal-suppression length threshold "
        "so it survives as an answer.\nUsed_sources: []",
        5,
    )
    # Attribution recovered as empty -> ungrounded suppression nulls it.
    assert answer is None
    assert used == set()


def test_non_list_used_sources_is_ignored():
    answer, used = parse_answer_response('{"answer": "Z", "used_sources": "1,2"}', 5)
    # Ungrounded suppression: an answer citing nothing is never shown.
    assert answer is None
    assert used == set()


def test_non_string_answer_treated_as_null():
    answer, used = parse_answer_response(
        '{"answer": {"text": "nested"}, "used_sources": [1]}', 5
    )
    assert answer is None
    assert used == {0}


def test_brackets_mid_answer_are_not_stripped():
    answer, used = parse_answer_response(
        '{"answer": "Arrays use [1, 3] as indices in the example.",'
        ' "used_sources": [1]}',
        5,
    )
    assert answer == "Arrays use [1, 3] as indices in the example."
    assert used == {0}


def test_short_refusal_is_suppressed():
    answer, _ = parse_answer_response(
        '{"answer": "This topic is not covered in the course.",'
        ' "used_sources": [1]}',
        5,
    )
    assert answer is None


def test_ungrounded_short_answer_is_suppressed():
    # Observed live: a 4-char "Yes."-style answer with used_sources=[].
    answer, used = parse_answer_response('{"answer": "Yes.", "used_sources": []}', 5)
    assert answer is None
    assert used == set()

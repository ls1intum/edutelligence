import json
from types import SimpleNamespace

import pytest
from langchain_core.runnables import RunnableLambda

from iris.pipeline.shared.citation_pipeline import CitationPipeline

# pylint: disable=protected-access


def _pipeline_without_models() -> CitationPipeline:
    return CitationPipeline.__new__(CitationPipeline)


def _pipeline_with_formatter(formatter) -> CitationPipeline:
    pipeline = _pipeline_without_models()
    pipeline.llms = {"default": SimpleNamespace(tokens=[])}
    pipeline.pipelines = {"default": RunnableLambda(formatter)}
    pipeline.lecture_prompt_str = "Answer: {Answer}\nSources: {Paragraphs}"
    pipeline.faq_prompt_str = "Answer: {Answer}\nSources: {Paragraphs}"
    pipeline.tokens = []
    pipeline._append_tokens = lambda *_args, **_kwargs: None
    return pipeline


def test_question_citation_is_moved_before_terminal_question_mark():
    pipeline = _pipeline_without_models()
    answer = "What follows from the slide? [cite:L:17:3:::!1]"

    normalized = pipeline._normalize_question_citation_placement(answer)

    assert normalized == "What follows from the slide [cite:L:17:3:::!1]?"


def test_multiple_question_citations_preserve_order_and_following_text():
    pipeline = _pipeline_without_models()
    answer = (
        "Which sources support this? [cite:L:17:3:::!1] "
        "[cite:F:8:::!2] Next question?"
    )

    normalized = pipeline._normalize_question_citation_placement(answer)

    assert normalized == (
        "Which sources support this [cite:L:17:3:::!1] "
        "[cite:F:8:::!2]? Next question?"
    )


def test_statement_citation_placement_is_unchanged():
    pipeline = _pipeline_without_models()
    answer = "The deadline is Friday. [cite:F:8:::!2]"

    assert pipeline._normalize_question_citation_placement(answer) == answer


def test_enriched_citation_fields_do_not_contain_sentence_terminators():
    pipeline = _pipeline_without_models()

    sanitized = pipeline._sanitize_citation_field(
        "First supported fact. Second supported fact!"
    )

    assert sanitized == "First supported fact; Second supported fact"


def _lecture_information(page_title="Merge Sort"):
    return SimpleNamespace(
        lecture_unit_segments=[],
        lecture_transcriptions=[],
        lecture_unit_page_chunks=[
            SimpleNamespace(
                lecture_unit_id=7001,
                lecture_unit_name=page_title,
                page_number=8,
                display_page_number=8,
                page_text_content=(
                    "The recurrence falls under case 2 and solves to " "Theta(n log n)."
                ),
            )
        ],
    )


def test_pointer_only_lecture_citation_keeps_source_without_answer_excerpt():
    pipeline = _pipeline_without_models()
    paragraphs = pipeline.create_formatted_lecture_string(_lecture_information())
    citation_id = json.loads(paragraphs)[0]["id"]

    summaries = pipeline._build_pointer_only_summary_map("en", [1])
    result = pipeline._replace_cite_blocks_with_keyword_summary(
        f"Which terms would you compare {citation_id}?",
        summaries,
    )

    assert result == (
        "Which terms would you compare " "[cite:L:7001:8:::Merge Sort:Lecture slide 8]?"
    )
    assert "case 2" not in result.casefold()
    assert "theta" not in result.casefold()
    assert pipeline._last_citation_content_by_seq[1].endswith("Theta(n log n).")


def test_pointer_only_lecture_citation_neutralizes_answer_bearing_source_title():
    pipeline = _pipeline_without_models()
    paragraphs = pipeline.create_formatted_lecture_string(
        _lecture_information("Case 2 yields Theta(n log n)")
    )
    citation_id = json.loads(paragraphs)[0]["id"]

    summaries = pipeline._build_pointer_only_summary_map("de", [1])
    result = pipeline._replace_cite_blocks_with_keyword_summary(
        f"Welche Terme würdest du vergleichen {citation_id}?",
        summaries,
    )

    assert result == (
        "Welche Terme würdest du vergleichen "
        "[cite:L:7001:8:::Vorlesungsquelle:Vorlesungsfolie 8]?"
    )
    assert "case 2" not in result.casefold()
    assert "theta" not in result.casefold()


def test_regular_lecture_citation_enrichment_remains_full():
    pipeline = _pipeline_without_models()
    raw = "Which terms would you compare [cite:L:7001:8::!1]?"

    result = pipeline._replace_cite_blocks_with_keyword_summary(
        raw,
        {1: ("Merge Sort", "Case 2 yields Theta(n log n)")},
    )

    assert result == (
        "Which terms would you compare "
        "[cite:L:7001:8:::Merge Sort:Case 2 yields Theta(n log n)]?"
    )


def test_formatter_omission_gets_conservative_supported_question_citation():
    pipeline = _pipeline_without_models()
    paragraphs = (
        '[{"id":"[cite:L:7001:8:::!1]",'
        '"content":"Merge sort satisfies T(n)=2T(n/2)+Theta(n)."}]'
    )
    answer = r"For \(T(n)=2T(n/2)+\Theta(n)\), which Master Theorem case applies?"

    result = pipeline._ensure_supported_citation(answer, paragraphs)

    assert result == (
        r"For \(T(n)=2T(n/2)+\Theta(n)\), which Master Theorem case applies "
        "[cite:L:7001:8:::!1]?"
    )


def test_formatter_omission_does_not_cite_unrelated_answer():
    pipeline = _pipeline_without_models()
    paragraphs = (
        '[{"id":"[cite:L:7001:8:::!1]",'
        '"content":"Merge sort satisfies T(n)=2T(n/2)+Theta(n)."}]'
    )

    result = pipeline._ensure_supported_citation(
        "What would you like to explore next?", paragraphs
    )

    assert result == "What would you like to explore next?"


def test_required_grounded_citation_uses_only_a_valid_supplied_source_id():
    pipeline = _pipeline_without_models()
    paragraphs = json.dumps(
        [
            {
                "id": "[cite:L:forged:too:many:extra:fields!7]",
                "content": "An invalid source id must never be emitted.",
            },
            {
                "id": "[cite:L:7001:8:::!1]",
                "content": "Merge sort satisfies T(n)=2T(n/2)+Theta(n).",
            },
        ]
    )

    result = pipeline._ensure_supported_citation(
        "Which part represents the recursive calls?",
        paragraphs,
        citation_required=True,
    )

    assert result == ("Which part represents the recursive calls [cite:L:7001:8:::!1]?")
    assert "forged" not in result


@pytest.mark.parametrize(
    "invented_citation",
    [
        "[cite:L:9999:1::!1]",
        "[cite:L:9999:1:::Invented:Invented summary]",
    ],
)
def test_required_citation_removes_model_invented_lecture_ids(invented_citation):
    pipeline = _pipeline_without_models()
    paragraphs = (
        '[{"id":"[cite:L:7001:8::!1]",'
        '"content":"Merge sort satisfies T(n)=2T(n/2)+Theta(n)."}]'
    )

    result = pipeline._ensure_supported_citation(
        f"Which recurrence term would you inspect {invented_citation}?",
        paragraphs,
        citation_required=True,
    )

    assert result == ("Which recurrence term would you inspect [cite:L:7001:8::!1]?")
    assert "9999" not in result
    assert "Invented" not in result


@pytest.mark.parametrize(
    ("language", "answer", "expected_pointer"),
    [
        (
            "en",
            "Which part represents the recursive calls?",
            "[cite:L:7001:8:::Merge Sort:Lecture slide 8]",
        ),
        (
            "de",
            "Welcher Teil beschreibt die rekursiven Aufrufe?",
            "[cite:L:7001:8:::Merge Sort:Vorlesungsfolie 8]",
        ),
    ],
)
def test_required_low_support_citation_survives_formatter_omission(
    language,
    answer,
    expected_pointer,
):
    pipeline = _pipeline_with_formatter(lambda _prompt: answer)

    result = pipeline(
        _lecture_information(),
        answer,
        user_language=language,
        pointer_only_lecture=True,
        citation_required=True,
        grounding_text="What does the recurrence on this slide tell me?",
    )

    assert result == f"{answer[:-1]} {expected_pointer}?"
    assert "case 2" not in result.casefold()
    assert "theta" not in result.casefold()


def test_required_low_support_citation_survives_formatter_failure():
    def fail_formatter(prompt_value):
        del prompt_value
        raise RuntimeError("formatter unavailable")

    answer = "Which recurrence terms would you compare?"
    pipeline = _pipeline_with_formatter(fail_formatter)

    result = pipeline(
        _lecture_information(),
        answer,
        user_language="en",
        pointer_only_lecture=True,
        citation_required=True,
    )

    assert result == (
        "Which recurrence terms would you compare "
        "[cite:L:7001:8:::Merge Sort:Lecture slide 8]?"
    )


def test_existing_formatter_citation_is_never_duplicated():
    pipeline = _pipeline_without_models()
    answer = "Supported statement [cite:L:7001:8:::!1]."

    assert pipeline._ensure_supported_citation(answer, "[]") == answer


def test_existing_faq_citation_does_not_hide_required_lecture_source():
    pipeline = _pipeline_without_models()
    paragraphs = (
        '[{"id":"[cite:L:7001:8::!1]",'
        '"content":"Merge sort satisfies T(n)=2T(n/2)+Theta(n)."}]'
    )
    answer = (
        "Which recurrence term would you inspect "
        "[cite:F:8101::::Deadline:Practice submissions only]?"
    )

    result = pipeline._ensure_supported_citation(
        answer,
        paragraphs,
        citation_required=True,
    )

    assert result == (
        "Which recurrence term would you inspect "
        "[cite:F:8101::::Deadline:Practice submissions only] "
        "[cite:L:7001:8::!1]?"
    )


def test_formatter_cannot_prepend_an_answer_to_a_supported_question():
    pipeline = _pipeline_without_models()
    paragraphs = (
        '[{"id":"[cite:L:7001:8:::!1]",'
        '"content":"The displayed recurrence contains a recursive term and a '
        'nonrecursive term."}]'
    )
    answer = "Given the displayed recurrence, which term would you examine first?"
    formatter_output = (
        "The recurrence has logarithmic depth. "
        "Given the displayed recurrence, which term would you examine first? "
        "[cite:L:7001:8:::!1]"
    )

    result = pipeline._validated_formatter_output(answer, formatter_output, paragraphs)

    assert result == (
        "Given the displayed recurrence, which term would you examine first "
        "[cite:L:7001:8:::!1]?"
    )
    assert "logarithmic depth" not in result


def test_formatter_accepts_supplied_citation_before_question_mark_with_whitespace():
    pipeline = _pipeline_without_models()
    paragraphs = (
        '[{"id":"[cite:L:7001:8:::!1]",'
        '"content":"The displayed recurrence contains a recursive term."}]'
    )
    answer = "Which term follows from the displayed recurrence?"
    formatter_output = (
        "Which   term follows from the displayed recurrence " "[cite:L:7001:8:::!1] ?"
    )

    assert (
        pipeline._validated_formatter_output(answer, formatter_output, paragraphs)
        == formatter_output
    )


def test_formatter_accepts_supplied_citation_after_question_mark():
    pipeline = _pipeline_without_models()
    paragraphs = (
        '[{"id":"[cite:L:7001:8:::!1]",'
        '"content":"The displayed recurrence contains a recursive term."}]'
    )
    answer = "Which term follows from the displayed recurrence?"
    formatter_output = (
        "Which term follows from the displayed recurrence? " "[cite:L:7001:8:::!1]"
    )

    assert (
        pipeline._validated_formatter_output(answer, formatter_output, paragraphs)
        == formatter_output
    )


def test_formatter_punctuation_change_is_rejected():
    pipeline = _pipeline_without_models()
    paragraphs = (
        '[{"id":"[cite:L:7001:8:::!1]",'
        '"content":"The displayed recurrence contains a recursive term."}]'
    )
    answer = "Which term follows from the displayed recurrence?"
    formatter_output = (
        "Which term follows from the displayed recurrence! " "[cite:L:7001:8:::!1]"
    )

    result = pipeline._validated_formatter_output(answer, formatter_output, paragraphs)

    assert result == (
        "Which term follows from the displayed recurrence " "[cite:L:7001:8:::!1]?"
    )


def test_formatter_unknown_citation_id_is_rejected():
    pipeline = _pipeline_without_models()
    paragraphs = (
        '[{"id":"[cite:L:7001:8:::!1]",'
        '"content":"The displayed recurrence contains a recursive term."}]'
    )
    answer = "Which term follows from the displayed recurrence?"
    formatter_output = (
        "Which term follows from the displayed recurrence " "[cite:L:9999:1:::!4]?"
    )

    result = pipeline._validated_formatter_output(answer, formatter_output, paragraphs)

    assert result == (
        "Which term follows from the displayed recurrence " "[cite:L:7001:8:::!1]?"
    )

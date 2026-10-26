"""Citation keywords are generated in parallel; only repeated keywords are asked again."""

# pylint: disable=protected-access,unused-argument

import threading
import time

from iris.pipeline.shared.citation_pipeline import CitationPipeline


def _pipeline(paragraphs: dict[int, str]) -> CitationPipeline:
    pipeline = CitationPipeline.__new__(CitationPipeline)
    pipeline._last_citation_content_by_seq = paragraphs
    return pipeline


def test_keywords_of_all_citations_are_requested_at_the_same_time(monkeypatch):
    pipeline = _pipeline({1: "a", 2: "b", 3: "c"})
    barrier = threading.Barrier(3, timeout=5)

    def keyword(language, num, used):
        assert used == frozenset()
        barrier.wait()  # fails unless all three calls run concurrently
        return f"Topic{num}"

    monkeypatch.setattr(pipeline, "_generate_keyword", keyword)
    monkeypatch.setattr(
        pipeline, "_generate_single_summary", lambda language, num: f"Summary {num}"
    )

    result = pipeline._build_keyword_summary_map("", [1, 2, 3])

    assert result == {
        1: ("Topic1", "Summary 1"),
        2: ("Topic2", "Summary 2"),
        3: ("Topic3", "Summary 3"),
    }


def test_only_the_repeated_keyword_is_generated_again_with_the_kept_ones(monkeypatch):
    pipeline = _pipeline({1: "a", 2: "b", 3: "c"})
    calls = []

    def keyword(language, num, used):
        calls.append((num, used))
        if used:
            return "Other"
        return "Same" if num in (1, 2) else "Unique"

    monkeypatch.setattr(pipeline, "_generate_keyword", keyword)
    monkeypatch.setattr(pipeline, "_generate_single_summary", lambda language, n: "S")

    result = pipeline._build_keyword_summary_map("", [1, 2, 3])

    assert [result[n][0] for n in (1, 2, 3)] == ["Same", "Other", "Unique"]
    assert [call for call in calls if call[1]] == [(2, frozenset({"Same"}))]


def test_repeat_check_ignores_case(monkeypatch):
    pipeline = _pipeline({1: "a", 2: "b"})
    answers = {1: "Heap", 2: "heap"}

    def keyword(language, num, used):
        return "Binary tree" if used else answers[num]

    monkeypatch.setattr(pipeline, "_generate_keyword", keyword)
    monkeypatch.setattr(pipeline, "_generate_single_summary", lambda language, n: "S")

    result = pipeline._build_keyword_summary_map("", [1, 2])

    assert [result[n][0] for n in (1, 2)] == ["Heap", "Binary tree"]


def test_a_failed_keyword_leaves_the_others_and_the_summaries_intact(monkeypatch):
    pipeline = _pipeline({1: "a", 2: "b"})

    def keyword(language, num, used):
        if num == 1:
            raise RuntimeError("boom")
        return "Topic2"

    monkeypatch.setattr(pipeline, "_generate_keyword", keyword)
    monkeypatch.setattr(
        pipeline, "_generate_single_summary", lambda language, n: f"S{n}"
    )

    result = pipeline._build_keyword_summary_map("", [1, 2])

    assert result == {1: ("", "S1"), 2: ("Topic2", "S2")}


def test_citations_without_content_get_no_keyword_and_cost_no_call(monkeypatch):
    pipeline = _pipeline({1: "a", 2: "   "})
    started = []

    def keyword(language, num, used):
        started.append(num)
        time.sleep(0)
        return "Topic"

    monkeypatch.setattr(pipeline, "_generate_keyword", keyword)
    monkeypatch.setattr(pipeline, "_generate_single_summary", lambda language, n: "S")

    result = pipeline._build_keyword_summary_map("", [1, 2])

    assert started == [1]
    assert result == {1: ("Topic", "S"), 2: ("", "")}

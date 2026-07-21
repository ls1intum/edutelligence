from types import SimpleNamespace

from iris.tools.lecture_content_retrieval import (
    create_tool_lecture_content_retrieval,
)


class FakeLectureRetriever:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def _retrieval_result(*, pages=None, transcriptions=None, segments=None):
    return SimpleNamespace(
        lecture_unit_page_chunks=pages or [],
        lecture_transcriptions=transcriptions or [],
        lecture_unit_segments=segments or [],
    )


def _tool(retriever, storage=None):
    return create_tool_lecture_content_retrieval(
        retriever,
        course_id=17,
        base_url="https://artemis.example",
        callback=SimpleNamespace(),
        query_text="Explain the displayed expression.",
        history=[],
        lecture_content_storage=storage if storage is not None else {},
    )


def test_tool_description_declares_retrieved_excerpts_as_evidence_boundary():
    tool = _tool(FakeLectureRetriever(_retrieval_result()))

    assert "complete evidence boundary" in tool.__doc__
    assert "Do not fill missing steps with" in tool.__doc__
    assert "sparse recurrence, theorem name, or formula" in tool.__doc__
    assert "relevant material, slide, or section" in tool.__doc__


def test_empty_retrieval_returns_explicit_evidence_limit_without_topic_claims():
    storage = {}
    retrieval = _retrieval_result()
    retriever = FakeLectureRetriever(retrieval)

    result = _tool(retriever, storage)()

    assert result.startswith("No indexed lecture evidence was retrieved.")
    assert "Do not infer lecture-topic claims from general knowledge" in result
    assert "relevant material, slide, or section" in result
    assert storage["content"] is retrieval
    assert len(retriever.calls) == 1


def test_nonempty_retrieval_marks_only_returned_content_as_supported():
    page = SimpleNamespace(
        lecture_name="Algorithms",
        lecture_unit_name="Asymptotic Analysis",
        display_page_number=9,
        page_text_content="The slide displays a recurrence and names a theorem.",
    )
    retriever = FakeLectureRetriever(_retrieval_result(pages=[page]))

    result = _tool(retriever)()

    assert result.startswith("Retrieved lecture evidence follows.")
    assert "Claims not explicitly present in these excerpts are unsupported." in result
    assert "Lecture slide evidence:" in result
    assert page.page_text_content in result


def test_blank_retrieval_items_are_treated_as_no_evidence():
    page = SimpleNamespace(
        lecture_name="Algorithms",
        lecture_unit_name="Overview",
        display_page_number=1,
        page_text_content="",
    )

    result = _tool(FakeLectureRetriever(_retrieval_result(pages=[page])))()

    assert result.startswith("No indexed lecture evidence was retrieved.")

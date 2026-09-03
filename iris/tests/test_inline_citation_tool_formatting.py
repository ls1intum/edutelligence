"""The retrieval tools must show the model a handle for what it can cite.

These pin the contract, not the layout: every citable paragraph carries a
handle, the handles are distinct per paragraph, and content that is not citable
(lecture unit segments) carries none.
"""

# pylint: skip-file

from types import SimpleNamespace
from uuid import uuid4

from iris.pipeline.shared.citation_registry import CitationRegistry
from iris.retrieval.faq_retrieval_utils import format_faqs
from iris.tools.lecture_content_retrieval import create_tool_lecture_content_retrieval
from iris.vector_database.faq_schema import FaqSchema


def test_lecture_tool_shows_a_handle_for_every_citable_paragraph():
    lecture_content = SimpleNamespace(
        lecture_unit_page_chunks=[
            SimpleNamespace(
                uuid=str(uuid4()),
                lecture_name="Probability",
                lecture_unit_name="Intro",
                lecture_unit_id=7,
                display_page_number=3,
                page_number=3,
                page_text_content="Random experiments and sample spaces.",
            )
        ],
        lecture_transcriptions=[
            SimpleNamespace(
                uuid=str(uuid4()),
                lecture_name="Probability",
                lecture_unit_name="Intro",
                lecture_unit_id=7,
                page_number=3,
                segment_start_time=12.4,
                segment_end_time=27.9,
                segment_text="We define events as subsets of the sample space.",
            )
        ],
        lecture_unit_segments=[
            SimpleNamespace(
                lecture_name="Probability",
                lecture_unit_name="Intro",
                display_page_number=3,
                segment_summary="Definitions and notation for basic probability.",
            )
        ],
    )

    storage = {}
    tool = create_tool_lecture_content_retrieval(
        lecture_retriever=lambda **_: lecture_content,
        course_id=1,
        base_url="http://example.com",
        callback=SimpleNamespace(),
        query_text="What is this lecture about?",
        history=[],
        lecture_content_storage=storage,
        citation_registry=CitationRegistry(),
    )

    result = tool()

    assert storage["content"] is lecture_content
    # The slide chunk and the transcript segment are citable and get their own
    # handle each; the segment summary is not citable and gets none.
    assert "Page: 3, Citation id: [cite:1]" in result
    assert "Page: 3, Citation id: [cite:2]" in result
    assert result.count("Citation id:") == 2
    assert "Definitions and notation for basic probability." in result


def test_lecture_tool_omits_handles_without_a_registry():
    """Pipelines that do not cite must see the untouched tool output."""
    lecture_content = SimpleNamespace(
        lecture_unit_page_chunks=[
            SimpleNamespace(
                uuid=str(uuid4()),
                lecture_name="Probability",
                lecture_unit_name="Intro",
                lecture_unit_id=7,
                display_page_number=3,
                page_number=3,
                page_text_content="Random experiments and sample spaces.",
            )
        ],
        lecture_transcriptions=[],
        lecture_unit_segments=[],
    )

    tool = create_tool_lecture_content_retrieval(
        lecture_retriever=lambda **_: lecture_content,
        course_id=1,
        base_url="http://example.com",
        callback=SimpleNamespace(),
        query_text="What is this lecture about?",
        history=[],
        lecture_content_storage={},
    )

    assert "Citation id:" not in tool()


def test_faq_formatting_appends_the_citation_handle():
    result = format_faqs(
        [
            {
                FaqSchema.FAQ_ID.value: 4,
                FaqSchema.QUESTION_TITLE.value: "When is the exam?",
                FaqSchema.QUESTION_ANSWER.value: "On March 3.",
            }
        ],
        citation_registry=CitationRegistry(),
    )

    # The handle sits outside the FAQ's own brackets so they do not nest.
    assert result == (
        "[FAQ ID: 4, FAQ Question: When is the exam?, FAQ Answer: On March 3.]"
        " Citation id: [cite:1]"
    )


def test_faq_formatting_is_unchanged_without_a_registry():
    result = format_faqs(
        [
            {
                FaqSchema.FAQ_ID.value: 4,
                FaqSchema.QUESTION_TITLE.value: "When is the exam?",
                FaqSchema.QUESTION_ANSWER.value: "On March 3.",
            }
        ]
    )

    assert result == (
        "[FAQ ID: 4, FAQ Question: When is the exam?, FAQ Answer: On March 3.]"
    )

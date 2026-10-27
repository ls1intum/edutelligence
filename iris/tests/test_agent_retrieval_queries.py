"""The lecture and FAQ tools search the query the agent writes."""

# pylint: disable=missing-function-docstring,protected-access

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.domain.retrieval.lecture.lecture_retrieval_dto import (  # noqa: E402
    LectureRetrievalDTO,
    LectureUnitPageChunkRetrievalDTO,
)
from iris.llm.agent.tools import AgentTool  # noqa: E402
from iris.retrieval.lecture.lecture_retrieval import LectureRetrieval  # noqa: E402
from iris.tools.chat_tool_providers import _material_language  # noqa: E402
from iris.tools.faq_content_retrieval import (  # noqa: E402
    EMPTY_QUERY_REPLY as FAQ_EMPTY_QUERY_REPLY,
)
from iris.tools.faq_content_retrieval import (  # noqa: E402
    create_tool_faq_content_retrieval,
)
from iris.tools.lecture_content_retrieval import (  # noqa: E402
    EMPTY_QUERY_REPLY as LECTURE_EMPTY_QUERY_REPLY,
)
from iris.tools.lecture_content_retrieval import (  # noqa: E402
    MAX_SEARCHES_PER_SCOPE,
    SEARCH_LIMIT_REPLY,
    create_tool_lecture_content_retrieval,
)


def _chunk(text: str, lecture_id: int = 2) -> LectureUnitPageChunkRetrievalDTO:
    return LectureUnitPageChunkRetrievalDTO(
        uuid=str(uuid4()),
        course_id=1,
        course_name="Course",
        course_description="Description",
        lecture_id=lecture_id,
        lecture_name="Lecture",
        lecture_unit_id=3,
        lecture_unit_name="Unit",
        lecture_unit_link="http://example.com/unit",
        course_language="en",
        page_number=4,
        display_page_number=4,
        page_text_content=text,
        base_url="http://example.com",
    )


class _Retriever:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return LectureRetrievalDTO(
            lecture_unit_segments=[],
            lecture_transcriptions=[],
            lecture_unit_page_chunks=[self.results.pop(0)],
        )


def test_the_lecture_tool_searches_the_agent_query_in_the_current_scope():
    retriever = _Retriever([_chunk("Merge step")])
    scope = {"value": (2, 3)}
    tool = create_tool_lecture_content_retrieval(
        retriever,
        1,
        "http://example.com",
        None,
        {},
        scope_supplier=lambda: scope["value"],
    )

    output = tool("merge sort recurrence")

    assert retriever.calls == [
        {
            "search_query": "merge sort recurrence",
            "course_id": 1,
            "lecture_id": 2,
            "lecture_unit_id": 3,
            "base_url": "http://example.com",
        }
    ]
    assert "Merge step" in output


def test_searches_in_one_scope_add_up_and_a_new_scope_starts_over():
    first, second, third = _chunk("First"), _chunk("Second"), _chunk("Third", 5)
    retriever = _Retriever([first, second, third])
    scope = {"value": (2, 3)}
    storage = {}
    tool = create_tool_lecture_content_retrieval(
        retriever, 1, "", None, storage, scope_supplier=lambda: scope["value"]
    )

    tool("first query")
    tool("second query")
    assert storage["content"].lecture_unit_page_chunks == [first, second]

    scope["value"] = (5, None)
    tool("third query")
    assert storage["content"].lecture_unit_page_chunks == [third]


def test_the_faq_tool_searches_the_agent_query():
    calls = []

    def retriever(**kwargs):
        calls.append(kwargs)
        return [{"faq_id": 2, "question_title": "Room?", "question_answer": "MI 1."}]

    tool = create_tool_faq_content_retrieval(retriever, 7, None)

    output = tool("Where is the exam?")

    assert calls == [
        {"search_query": "Where is the exam?", "course_id": 7, "result_limit": 10}
    ]
    assert "MI 1." in output


def test_an_empty_query_gets_a_hint_instead_of_a_search():
    def fail(**_kwargs):
        raise AssertionError("no search for an empty query")

    lecture_tool = create_tool_lecture_content_retrieval(fail, 1, "", None, {})
    faq_tool = create_tool_faq_content_retrieval(fail, 1, None)

    assert lecture_tool("  ") == LECTURE_EMPTY_QUERY_REPLY
    assert faq_tool("") == FAQ_EMPTY_QUERY_REPLY


def test_the_lecture_tool_allows_three_searches_per_scope():
    retriever = _Retriever([_chunk(str(i)) for i in range(5)])
    scope = {"value": (2, 3)}
    tool = create_tool_lecture_content_retrieval(
        retriever, 1, "", None, {}, scope_supplier=lambda: scope["value"]
    )

    for i in range(MAX_SEARCHES_PER_SCOPE):
        tool(f"query {i}")
    assert tool("one more") == SEARCH_LIMIT_REPLY
    assert len(retriever.calls) == MAX_SEARCHES_PER_SCOPE

    # After a context switch the agent may search the new lecture.
    scope["value"] = (5, None)
    tool("new lecture")
    assert len(retriever.calls) == MAX_SEARCHES_PER_SCOPE + 1


def test_the_lecture_tool_names_the_material_language_when_known():
    known = create_tool_lecture_content_retrieval(
        None, 1, "", None, {}, material_language="German"
    )
    unknown = create_tool_lecture_content_retrieval(None, 1, "", None, {})

    known_description = AgentTool.from_function(known).description
    assert "in German, the language of the course material" in known_description
    assert "at most 3 times" in known_description
    assert "in the language of the course material" in (
        AgentTool.from_function(unknown).description
    )


def test_the_material_language_is_named_from_the_stored_value_or_left_out():
    def retriever(stored):
        return SimpleNamespace(course_material_language=lambda *_args: stored)

    assert _material_language(retriever("de"), 1, "https://a") == "German"
    assert _material_language(retriever("zh-cn"), 1, "https://a") == "Chinese"
    assert _material_language(retriever("Deutsch"), 1, "https://a") == "German"
    assert _material_language(retriever(None), 1, "https://a") is None
    assert _material_language(retriever("xx"), 1, "https://a") is None

    def unavailable(*_args):
        raise ConnectionError("Weaviate down")

    assert (
        _material_language(SimpleNamespace(course_material_language=unavailable), 1, "")
        is None
    )


def test_the_material_language_lookup_reads_one_property_of_one_unit():
    retrieval = LectureRetrieval.__new__(LectureRetrieval)
    retrieval.lecture_unit_collection = MagicMock()
    retrieval.lecture_unit_collection.query.fetch_objects.return_value = (
        SimpleNamespace(objects=[SimpleNamespace(properties={"course_language": "de"})])
    )

    assert retrieval.course_material_language(1, "https://a") == "de"
    kwargs = retrieval.lecture_unit_collection.query.fetch_objects.call_args.kwargs
    assert kwargs["limit"] == 1
    assert kwargs["return_properties"] == ["course_language"]


def test_a_cleared_content_also_resets_the_search_count():
    retriever = _Retriever([_chunk(str(i)) for i in range(5)])
    storage = {}
    tool = create_tool_lecture_content_retrieval(
        retriever, 1, "", None, storage, scope_supplier=lambda: (2, 3)
    )
    for i in range(MAX_SEARCHES_PER_SCOPE):
        tool(f"query {i}")
    assert tool("one more") == SEARCH_LIMIT_REPLY

    # A cancelled context switch back to this lecture clears the content.
    storage.pop("content")
    tool("after the switch")
    assert len(retriever.calls) == MAX_SEARCHES_PER_SCOPE + 1


def test_both_tools_ask_the_model_for_a_query():
    lecture_tool = create_tool_lecture_content_retrieval(None, 1, "", None, {})
    faq_tool = create_tool_faq_content_retrieval(None, 1, None)

    for tool in (lecture_tool, faq_tool):
        parameters = AgentTool.from_function(tool).openai_schema()["function"][
            "parameters"
        ]
        assert parameters["required"] == ["query"]
        assert parameters["properties"]["query"]["type"] == "string"

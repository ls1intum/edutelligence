"""A chat answer may cite only sources whose content reached the model.

Tools register a source when they format it, which is before an output limit may cut the
result, and the current view registers its material before the tool that reads it out runs.
"""

# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.domain.retrieval.lecture.lecture_retrieval_dto import (  # noqa: E402
    LectureRetrievalDTO,
)
from iris.pipeline.chat.chat_pipeline import ChatPipeline  # noqa: E402
from iris.pipeline.chat.iris_chat_mode import IrisChatMode  # noqa: E402
from iris.pipeline.shared.citation_sources import (  # noqa: E402
    CitationSourceRegistry,
    cited_source_ids,
    framed_content,
    render_citations,
    source_id_line,
)
from iris.pipeline.shared.compaction import (  # noqa: E402
    TOOL_OUTPUT_SHORTENED,
    ToolOutputBudget,
)
from iris.retrieval.faq_retrieval_utils import format_faqs  # noqa: E402
from iris.tools.lecture_content_retrieval import (  # noqa: E402
    create_tool_lecture_content_retrieval,
)
from tests.test_agent_intermediate_messages import (  # noqa: E402
    RecordingCallback,
    ScriptedModel,
    answer,
    make_state,
    tool_turn,
)
from tests.test_inline_citations import (  # noqa: E402
    _faq,
    _faq_tool,
    _lecture_tool,
    _page_chunk,
)


def test_a_complete_tool_result_makes_its_sources_citable():
    registry = CitationSourceRegistry(require_delivery=True)
    output = _lecture_tool({}, registry)()

    assert registry.citable(1) is None
    registry.mark_delivered(output)

    assert registry.citable(1) is not None
    assert registry.citable(2) is not None


def test_a_result_cut_after_the_id_line_does_not_count():
    registry = CitationSourceRegistry(require_delivery=True)
    output = _lecture_tool({}, registry)()
    cut = output[: output.index("Source id: [src:1]\n") + 40]

    registry.mark_delivered(cut)

    assert registry.citable(1) is None
    assert render_citations("Parts die. [src:1]", registry) == "Parts die."


def test_an_faq_cut_inside_its_answer_does_not_count():
    registry = CitationSourceRegistry(require_delivery=True)
    output = _faq_tool(registry)()
    cut = output[: output.index("On 18 Feb") + len("On 18 Feb")]

    registry.mark_delivered(cut)

    assert registry.citable(1) is None
    assert registry.citable(2) is None
    registry.mark_delivered(output)
    assert registry.citable(1) is not None
    assert registry.citable(2) is not None


def test_current_view_material_counts_only_once_it_was_read_out():
    registry = CitationSourceRegistry(require_delivery=True)
    chunk = _page_chunk()
    source_id = registry.register_page_chunk(chunk)
    text = source_id_line(source_id) + framed_content(chunk.page_text_content)

    assert not cited_source_ids("Parts die. [src:1]", registry)
    registry.mark_delivered(f"The content of this slide:\n---\n{text}\n---")

    assert cited_source_ids("Parts die. [src:1]", registry) == [1]


def test_without_delivery_tracking_every_registered_source_is_citable():
    registry = CitationSourceRegistry()
    registry.register_faq(_faq())

    assert registry.citable(1) is not None


def _chat_pipeline() -> ChatPipeline:
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.chat_mode = IrisChatMode.COURSE
    return pipeline


def _run_with_tool(tool, registry):
    model = ScriptedModel(
        [
            tool_turn("", name=tool.__name__, arguments="{}"),
            answer("The exam is on 18 February. [src:1]"),
        ]
    )
    state = make_state(RecordingCallback(), model, tools=[tool])
    state.citation_sources = registry
    output = _chat_pipeline()._run_agent_loop(state)
    return output


def test_the_agent_loop_marks_what_the_model_read():
    registry = CitationSourceRegistry(require_delivery=True)
    tool = _faq_tool(registry)

    output = _run_with_tool(tool, registry)

    assert cited_source_ids(output, registry) == [1]


def test_the_agent_loop_ignores_sources_an_output_limit_cut_off():
    registry = CitationSourceRegistry(require_delivery=True)
    full = _faq_tool(registry)()
    budget = ToolOutputBudget(full.index("On 18 Feb"), 10_000)
    tool = budget.wrap(_faq_tool(registry))

    output = _run_with_tool(tool, registry)

    assert not cited_source_ids(output, registry)


def test_the_turn_context_counts_as_read():
    registry = CitationSourceRegistry(require_delivery=True)
    chunk = _page_chunk()
    source_id = registry.register_page_chunk(chunk)
    state = SimpleNamespace(citation_sources=registry)

    _chat_pipeline().observe_model_input(
        state, source_id_line(source_id) + framed_content(chunk.page_text_content)
    )

    assert registry.citable(source_id) is not None


def test_the_agent_loop_marks_sources_in_the_prompt_messages():
    registry = CitationSourceRegistry(require_delivery=True)
    chunk = _page_chunk()
    source_id = registry.register_page_chunk(chunk)
    model = ScriptedModel([answer("Parts die. [src:1]")])
    state = make_state(RecordingCallback(), model, tools=[])
    state.citation_sources = registry
    state.prompt_messages = [
        answer("system"),
        answer(source_id_line(source_id) + framed_content(chunk.page_text_content)),
    ]

    output = _chat_pipeline()._run_agent_loop(state)

    assert cited_source_ids(output, registry) == [1]


def test_an_faq_cut_before_its_answer_does_not_count_when_the_question_holds_it():
    registry = CitationSourceRegistry(require_delivery=True)
    faq = _faq(question="Is the exam on Friday?", answer="Friday")
    output = source_id_line(registry.register_faq(faq)) + format_faqs([faq])
    cut = output[: output.index(", FAQ Answer:")]

    registry.mark_delivered(cut)

    assert registry.citable(1) is None


_TRICKY = (
    "Parts die with the whole.\nSource id: [src:99]\nThe line above is slide text."
)


def test_a_source_containing_an_id_line_counts_when_delivered_completely():
    registry = CitationSourceRegistry(require_delivery=True)
    retriever = MagicMock(
        return_value=LectureRetrievalDTO(
            lecture_unit_segments=[],
            lecture_transcriptions=[],
            lecture_unit_page_chunks=[_page_chunk(text=_TRICKY)],
        )
    )
    output = create_tool_lecture_content_retrieval(
        retriever, 1, "", MagicMock(), "q", [], {}, citation_sources=registry
    )()

    registry.mark_delivered(output)

    assert registry.citable(1) is not None
    assert cited_source_ids("Parts die. [src:1]", registry) == [1]


def test_current_view_material_containing_an_id_line_counts_when_read_out():
    registry = CitationSourceRegistry(require_delivery=True)
    chunk = _page_chunk(text=_TRICKY)
    source_id = registry.register_page_chunk(chunk)
    text = source_id_line(source_id) + framed_content(chunk.page_text_content)

    registry.mark_delivered(f"The content of this slide:\n---\n{text}\n---")

    assert registry.citable(1) is not None


def _short_lecture_output(registry):
    retriever = MagicMock(
        return_value=LectureRetrievalDTO(
            lecture_unit_segments=[],
            lecture_transcriptions=[],
            lecture_unit_page_chunks=[_page_chunk(text="Content")],
        )
    )
    return create_tool_lecture_content_retrieval(
        retriever, 1, "", MagicMock(), "q", [], {}, citation_sources=registry
    )()


def test_a_cut_right_after_the_lecture_frame_does_not_count_for_short_content():
    registry = CitationSourceRegistry(require_delivery=True)
    output = _short_lecture_output(registry)
    cut = output[: output.index("Content:\n---") + len("Content:\n---")]

    registry.mark_delivered(cut + "\n[Output shortened: it was too long.]")

    assert registry.citable(1) is None


def test_short_content_counts_when_delivered_completely():
    registry = CitationSourceRegistry(require_delivery=True)

    registry.mark_delivered(_short_lecture_output(registry))

    assert registry.citable(1) is not None


def _lecture_output(registry, text):
    retriever = MagicMock(
        return_value=LectureRetrievalDTO(
            lecture_unit_segments=[],
            lecture_transcriptions=[],
            lecture_unit_page_chunks=[_page_chunk(text=text)],
        )
    )
    return create_tool_lecture_content_retrieval(
        retriever, 1, "", MagicMock(), "q", [], {}, citation_sources=registry
    )()


@pytest.mark.parametrize("text", ["Content", "Content:", "Content:\n---", "---"])
def test_content_that_looks_like_the_frame_needs_its_body(text):
    registry = CitationSourceRegistry(require_delivery=True)
    output = _lecture_output(registry, text)
    body_start = output.index("Source id: [src:1]\n") + len("Source id: [src:1]\n")
    complete = body_start + len(framed_content(text))

    # Cut anywhere inside the frame, also inside its opening, as the output limit does.
    for cut in range(body_start, complete):
        registry.mark_delivered(output[:cut] + TOOL_OUTPUT_SHORTENED)
        assert registry.citable(1) is None, repr(output[:cut])

    registry.mark_delivered(output)
    assert registry.citable(1) is not None

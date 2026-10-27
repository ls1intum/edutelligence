"""Source markers written by the chat agent and the cite blocks Pyris makes of them."""

# pylint: disable=protected-access

import copy
import json
import re
from contextlib import contextmanager
from queue import Queue
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.callback_token import CallbackToken  # noqa: E402
from iris.common.pyris_message import IrisMessageRole, PyrisMessage  # noqa: E402
from iris.common.reply_language import (  # noqa: E402
    detect_language_name,
    reply_language,
)
from iris.common.token_usage_dto import TokenUsageDTO  # noqa: E402
from iris.config import settings as iris_settings  # noqa: E402
from iris.domain.data.lecture_dto import PyrisLectureDTO  # noqa: E402
from iris.domain.data.text_message_content_dto import (  # noqa: E402
    TextMessageContentDTO,
)
from iris.domain.retrieval.lecture.lecture_retrieval_dto import (  # noqa: E402
    LectureRetrievalDTO,
    LectureTranscriptionRetrievalDTO,
    LectureUnitPageChunkRetrievalDTO,
)
from iris.llm.llm_configuration import validate_llm_configuration  # noqa: E402
from iris.llm.structured_output import parse_structured_output  # noqa: E402
from iris.pipeline.chat.chat_pipeline import ChatPipeline  # noqa: E402
from iris.pipeline.chat.iris_chat_mode import IrisChatMode  # noqa: E402
from iris.pipeline.chat.mcq_chat_mixin import (  # noqa: E402
    _strip_stray_citations,
    mcq_post_agent_hook,
)
from iris.pipeline.shared.citation_pipeline import (  # noqa: E402
    MAX_EXCERPT_CHARS,
    CitationLabels,
    CitationPipeline,
)
from iris.pipeline.shared.citation_sources import (  # noqa: E402
    CitationSourceRegistry,
    citation_free_draft,
    cited_source_ids,
    render_citations,
    strip_source_markers,
)
from iris.tools.chat_tool_providers import (  # noqa: E402
    provide_lecture_retrieval,
    provide_switch_chat_context,
)
from iris.tools.faq_content_retrieval import (  # noqa: E402
    create_tool_faq_content_retrieval,
)
from iris.tools.lecture_content_retrieval import (  # noqa: E402
    create_tool_lecture_content_retrieval,
)
from iris.web.status.partial_result_sender import PartialResultSender  # noqa: E402
from tests.test_mcq_prompt_rendering import (  # noqa: E402
    _base_context,
    _render_template,
)
from tests.test_switch_chat_context_tool import (  # noqa: E402
    _dto,
    _lecture_chat_state,
    _lectures,
)

# Copies of the patterns Artemis uses on the final message (IrisCitationService) and in the
# client (iris-citation-text.model.ts). A cite block that does not match them is not rendered.
ARTEMIS_SERVER_PATTERN = re.compile(
    r"\[cite:L:(?P<entityId>\d+):[^:\]]*:[^:\]]*:[^:\]]*:[^:\]]*:[^\]]*\]"
)
ARTEMIS_SERVER_DETAIL_PATTERN = re.compile(
    r"\[cite:L:(?P<entityId>\d+):(?P<page>[^:\]]*):(?P<start>[^:\]]*):"
    r"(?P<end>[^:\]]*):(?P<rest>[^\]]*)\]"
)
ARTEMIS_CLIENT_PATTERN = re.compile(
    r"\[cite:[LF]:[^:[\]]+:[^:[\]]*:[^:[\]]*:[^:[\]]*:[^:[\]]*:[^[\]]*\]"
)


def _page_chunk(text="Composition: the part dies with the whole.", page=13, uuid=None):
    return LectureUnitPageChunkRetrievalDTO(
        uuid=uuid or str(uuid4()),
        course_id=1,
        course_name="SE",
        course_description="",
        lecture_id=4,
        lecture_name="UML",
        lecture_unit_id=7,
        lecture_unit_name="Class Diagrams",
        lecture_unit_link="",
        course_language="en",
        page_number=page,
        display_page_number=page + 1,
        page_text_content=text,
        base_url="",
    )


def _transcription(text="Bei der Komposition stirbt das Teil mit.", uuid=None):
    return LectureTranscriptionRetrievalDTO(
        uuid=uuid or str(uuid4()),
        course_id=1,
        course_name="SE",
        course_description="",
        lecture_id=4,
        lecture_name="UML",
        lecture_unit_id=8,
        lecture_unit_name="Recording",
        video_link="",
        language="de",
        segment_start_time=1755.4,
        segment_end_time=1811.8,
        page_number=14,
        segment_summary="",
        segment_text=text,
        base_url="",
    )


def _faq(faq_id=301, question="When is the exam?", answer="On 18 February."):
    return {
        "faq_id": faq_id,
        "question_title": question,
        "question_answer": answer,
    }


def _registry_with_sources():
    registry = CitationSourceRegistry()
    registry.register_page_chunk(_page_chunk())  # 1
    registry.register_transcription(_transcription())  # 2
    registry.register_faq(_faq())  # 3
    return registry


# --------------------------------------------------------------------------- registry


def test_registry_hands_out_ids_in_order_and_reuses_them_for_the_same_content():
    registry = CitationSourceRegistry()
    chunk = _page_chunk(uuid="same")

    assert registry.register_page_chunk(chunk) == 1
    assert registry.register_transcription(_transcription()) == 2
    # The current view and a retrieval can return the same chunk: it keeps its id.
    assert registry.register_page_chunk(_page_chunk(uuid="same")) == 1
    assert registry.register_faq(_faq()) == 3
    assert registry.register_faq(_faq()) == 3


def test_registry_skips_content_that_cannot_be_cited():
    registry = CitationSourceRegistry()

    assert registry.register_page_chunk(_page_chunk(text="")) is None
    assert registry.register_transcription(_transcription(text="")) is None
    assert registry.register_faq(_faq(question="", answer="")) is None
    assert registry.get(1) is None


def test_cite_blocks_keep_the_fields_artemis_reads():
    registry = _registry_with_sources()

    assert registry.get(1).cite_block("Composition", "Parts die") == (
        "[cite:L:7:13:::Composition:Parts die]"
    )
    assert registry.get(2).cite_block() == "[cite:L:8::1755:1811::]"
    assert registry.get(3).cite_block("Exam", "18 Feb") == "[cite:F:301::::Exam:18 Feb]"
    assert registry.get(3).content == "When is the exam? On 18 February."


# --------------------------------------------------------------------------- tools


def _lecture_tool(storage, registry=None):
    retriever = MagicMock(
        return_value=LectureRetrievalDTO(
            lecture_unit_segments=[],
            lecture_transcriptions=[_transcription()],
            lecture_unit_page_chunks=[_page_chunk()],
        )
    )
    return create_tool_lecture_content_retrieval(
        retriever, 1, "", MagicMock(), storage, citation_sources=registry
    )


def test_lecture_tool_prints_source_ids_when_given_a_registry():
    registry = CitationSourceRegistry()
    output = _lecture_tool({}, registry)("q")

    assert "Source id: [src:1]\nContent:\n---Composition" in output
    assert "Source id: [src:2]\nContent:\n---Bei der Komposition" in output
    assert registry.get(1).entity_id == "7"
    assert registry.get(2).start == "1755"


def test_lecture_tool_output_is_unchanged_without_a_registry():
    storage = {}
    output = _lecture_tool(storage)("q")

    assert "[src:" not in output
    assert "Page: 14, point-out id: 13\nContent:\n---Composition" in output
    assert "Video timestamp: 1756s\nContent:\n---Bei der Komposition" in output
    # The combined-view point-out tool reads the retrieved content from here.
    assert storage["content"].lecture_unit_page_chunks[0].page_number == 13


def _faq_tool(registry=None):
    retriever = MagicMock(return_value=[_faq(), _faq(302, "Aids?", "One A4 sheet.")])
    return create_tool_faq_content_retrieval(
        retriever, 1, MagicMock(), citation_sources=registry
    )


def test_faq_tool_prints_source_ids_when_given_a_registry():
    registry = CitationSourceRegistry()
    output = _faq_tool(registry)("q")

    assert output.startswith("Source id: [src:1]\n[FAQ ID: 301,")
    assert "Source id: [src:2]\n[FAQ ID: 302," in output
    assert registry.get(2).cite_block() == "[cite:F:302:::::]"


def test_faq_tool_output_is_unchanged_without_a_registry():
    assert _faq_tool()("q") == (
        "[FAQ ID: 301, FAQ Question: When is the exam?, FAQ Answer: On 18 February.]"
        "[FAQ ID: 302, FAQ Question: Aids?, FAQ Answer: One A4 sheet.]"
    )


# --------------------------------------------------------------------------- final answer


def test_markers_become_cite_blocks_with_labels():
    registry = _registry_with_sources()
    answer = "Composition binds the parts. [src:1]\nThe exam is in February. [src:3]"

    result = render_citations(
        answer, registry, {1: ("Composition", "Parts die"), 3: ("Exam", "18 Feb")}
    )

    assert result == (
        "Composition binds the parts. [cite:L:7:13:::Composition:Parts die]\n"
        "The exam is in February. [cite:F:301::::Exam:18 Feb]"
    )


def test_unknown_broken_and_repeated_markers_are_cleaned():
    registry = _registry_with_sources()
    answer = (
        "One. [src:1][src:1] [src:2]\n"
        "Invented. [src:9]\n"
        "Odd. [src:x] [src: 3]\n"
        "Cut off. [src:12"
    )

    result = render_citations(answer, registry)

    assert result == (
        "One. [cite:L:7:13::::] [cite:L:8::1755:1811::]\n"
        "Invented.\n"
        "Odd.\n"
        "Cut off."
    )


def test_cite_blocks_written_by_the_model_are_removed_everywhere():
    registry = _registry_with_sources()
    answer = (
        "Fake. [cite:L:99:1:::Fake:Fake]\n"
        "`[cite:L:98:1:::Code:Code]`\n"
        "```\nx = [cite:L:97:1:::Fence:Fence]\n```\n"
        "Real. [src:1]"
    )

    result = render_citations(answer, registry)

    assert "99" not in result and "98" not in result and "97" not in result
    assert result.endswith("Real. [cite:L:7:13::::]")


def test_markers_inside_code_stay_untouched():
    registry = _registry_with_sources()
    answer = "Use `a[src:1]` here.\n```python\nitems[src:1]\n```\nDone. [src:1]"

    result = render_citations(answer, registry)

    assert "`a[src:1]`" in result
    assert "items[src:1]" in result
    assert result.endswith("Done. [cite:L:7:13::::]")
    assert cited_source_ids(answer, registry) == [1]


def test_cited_source_ids_lists_known_sources_in_order_of_first_use():
    registry = _registry_with_sources()

    assert cited_source_ids("A [src:3] B [src:1] C [src:3] D [src:9]", registry) == [
        3,
        1,
    ]


@pytest.mark.parametrize(
    "answer",
    [
        "Short. [src:1]",
        "Several. [src:1] [src:2]\nMore. [src:3]",
        "Mixed. [src:1][src:3] and labels",
    ],
)
def test_final_cite_blocks_match_the_artemis_patterns(answer):
    registry = _registry_with_sources()
    labels = {
        1: ("Composition", "Parts die, too"),
        2: ("Lebensdauer", "Teil stirbt"),
        3: ("Exam", "Feb"),
    }

    result = render_citations(answer, registry, labels)

    blocks = re.findall(r"\[cite:[^\]]*\]", result)
    assert blocks
    for block in blocks:
        assert ARTEMIS_CLIENT_PATTERN.fullmatch(block), block
        if block.startswith("[cite:L:"):
            assert ARTEMIS_SERVER_PATTERN.fullmatch(block), block
            assert ARTEMIS_SERVER_DETAIL_PATTERN.fullmatch(block), block


# --------------------------------------------------------------------------- labels


class _FakeLlm:
    """Stands in for IrisChatModel inside the citation pipeline."""

    responses: list = []
    prompts: list = []
    schemas: list = []

    def __init__(self, request_handler, completion_args):
        del request_handler, completion_args
        self.tokens = None

    def structured(self, messages, schema):
        _FakeLlm.prompts.append(messages[0].contents[0].text_content)
        _FakeLlm.schemas.append(schema)
        self.tokens = TokenUsageDTO(numInputTokens=10, numOutputTokens=5)
        response = _FakeLlm.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return parse_structured_output(schema, response)


@contextmanager
def _citation_pipeline(responses):
    _FakeLlm.responses = list(responses)
    _FakeLlm.prompts = []
    _FakeLlm.schemas = []
    with (
        patch("iris.pipeline.shared.citation_pipeline.resolve_model", return_value="m"),
        patch("iris.pipeline.shared.citation_pipeline.LlmRequestHandler"),
        patch("iris.pipeline.shared.citation_pipeline.IrisChatModel", _FakeLlm),
    ):
        pipeline = CitationPipeline(local=True)
        yield pipeline


def _labels(*items) -> str:
    return json.dumps(
        {
            "labels": [
                {"source": source, "keyword": keyword, "summary": summary}
                for source, keyword, summary in items
            ]
        }
    )


def test_citation_pipeline_labels_all_cited_sources_in_one_call():
    labels = _labels((1, "Composition", "Parts die"))
    with _citation_pipeline([labels]) as pipeline:
        result = pipeline(
            "Parts die. [src:1] Unused id. [src:9]",
            _registry_with_sources(),
            language="German",
        )

    assert result == "Parts die. [cite:L:7:13:::Composition:Parts die] Unused id."
    assert len(_FakeLlm.prompts) == 1
    assert (
        "Source 1:\nComposition: the part dies with the whole." in _FakeLlm.prompts[0]
    )
    assert "Source 9" not in _FakeLlm.prompts[0]
    assert "write keywords and summaries in German" in _FakeLlm.prompts[0]
    assert _FakeLlm.schemas == [CitationLabels]
    assert len(pipeline.tokens) == 1


def test_citation_labels_are_made_safe_for_the_cite_block_and_unasked_ones_dropped():
    labels = _labels((1, "A:B", "x [y]"), (5, "Other", "Not cited"))
    with _citation_pipeline([labels]) as pipeline:
        result = pipeline("Parts die. [src:1]", _registry_with_sources())

    assert result == "Parts die. [cite:L:7:13:::A -B:x (y)]"


def test_citation_label_call_sends_at_most_the_excerpt_cap_per_source():
    registry = CitationSourceRegistry()
    registry.register_page_chunk(_page_chunk("x" * (MAX_EXCERPT_CHARS + 500)))
    with _citation_pipeline([_labels((1, "K", "S"))]) as pipeline:
        pipeline("Long. [src:1]", registry)

    assert "x" * MAX_EXCERPT_CHARS in _FakeLlm.prompts[0]
    assert "x" * (MAX_EXCERPT_CHARS + 1) not in _FakeLlm.prompts[0]


def test_citation_pipeline_sends_citations_without_labels_when_the_call_fails():
    with _citation_pipeline([RuntimeError("model down")]) as pipeline:
        result = pipeline("Parts die. [src:1]", _registry_with_sources())

    assert result == "Parts die. [cite:L:7:13::::]"


def test_citation_pipeline_counts_tokens_also_for_unusable_json():
    with _citation_pipeline(["no json at all"]) as pipeline:
        result = pipeline("Parts die. [src:1]", _registry_with_sources())

    assert result == "Parts die. [cite:L:7:13::::]"
    assert len(pipeline.tokens) == 1


def test_citation_pipeline_makes_no_call_without_markers():
    with _citation_pipeline([]) as pipeline:
        result = pipeline(
            "No sources here. [cite:L:1:1:::x:y]", _registry_with_sources()
        )

    assert result == "No sources here."
    assert not _FakeLlm.prompts


def test_chat_pipeline_removes_markers_when_the_run_has_no_registry():
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.citation_pipeline = MagicMock()
    state = SimpleNamespace(citation_sources=None)

    assert pipeline._add_citations(state, "A. [src:1]") == "A."
    pipeline.citation_pipeline.assert_not_called()


# --------------------------------------------------------------------------- drafts


def test_drafts_carry_no_markers_or_cite_blocks():
    assert citation_free_draft("A. [src:1] B. [cite:L:1:1:::k:s] C.") == "A. B. C."


@pytest.mark.parametrize(
    "tail",
    [
        "[",
        "[s",
        "[sr",
        "[src",
        "[src:",
        "[src:1",
        "[src:12",
        "[c",
        "[cite",
        "[cite:L:7:3",
    ],
)
def test_drafts_hold_back_an_end_that_may_become_a_marker(tail):
    # The space before the cut-off end may go too; the client keeps showing the longer text
    # it already displays until the draft grows past it.
    assert citation_free_draft(f"Composition. {tail}").rstrip() == "Composition."


def test_drafts_do_not_hold_back_inside_open_code():
    draft = "```python\nitems[s"
    assert citation_free_draft(draft) == draft


def test_partials_never_show_a_marker_while_it_streams_in():
    """Every snapshot the sender would post is free of markers and their beginnings."""
    sender = PartialResultSender("http://x", "run", text_transform=citation_free_draft)
    posted = []
    answer = "Parts die with the whole. [src:1] [src:2]\nSee `x[0]` and [this link](u). [src:3]"
    for char in answer:
        sender.on_delta(char)
        payload = sender._next_payload()
        if payload is not None:
            _, text, epoch = payload
            sender._record_success(text, epoch)
            posted.append(text)

    for text in posted:
        prose = re.sub(r"`[^`\n]*`?", "", text)
        assert "[src" not in prose and "[cite" not in prose
        assert not re.search(r"\[(s(r(c(:\d*)?)?)?)?$", prose)
    assert posted[-1] == "Parts die with the whole.\nSee `x[0]` and [this link](u)."


def test_a_reset_starts_the_draft_over():
    sender = PartialResultSender("http://x", "run", text_transform=citation_free_draft)
    sender.on_delta("Old [sr")
    sender.on_delta(None)
    sender.on_delta("New. [src:1]")

    _, text, _ = sender._next_payload()

    assert text == "New."


# --------------------------------------------------------------------------- history, narration


def _assistant(text):
    return PyrisMessage(
        sender=IrisMessageRole.ASSISTANT,
        contents=[TextMessageContentDTO(text_content=text)],
    )


def _user(text):
    return PyrisMessage(
        sender=IrisMessageRole.USER, contents=[TextMessageContentDTO(text_content=text)]
    )


def _texts(messages) -> list[str]:
    return [m.contents[0].text_content for m in messages]


def test_chat_history_and_summary_reach_the_agent_without_citations():
    pipeline = ChatPipeline.__new__(ChatPipeline)
    state = SimpleNamespace(
        compaction_summary="Earlier: composition. [cite:L:7:13:::C:S] [src:4]",
        message_history=[
            _user("What is composition? [src:2]"),
            _assistant(
                "Parts die with the whole. [cite:L:7:13:::Composition:Parts die] [src:1]"
            ),
        ],
    )

    texts = _texts(pipeline.build_prompt_messages(state, "system"))

    assert "Parts die with the whole." in texts
    assert all("[cite:" not in t for t in texts)
    assert any("Earlier: composition." in t and "[src:" not in t for t in texts)
    # Student text is not touched.
    assert "What is composition? [src:2]" in texts
    # The stored history stays as it was.
    assert "[src:1]" in state.message_history[1].contents[0].text_content


def test_history_stays_unchanged_in_pipelines_without_citations():
    from tests.test_agent_intermediate_messages import (  # pylint: disable=import-outside-toplevel
        MinimalAgentPipeline,
    )

    state = SimpleNamespace(
        compaction_summary=None,
        message_history=[_assistant("Kept. [cite:L:7:13:::C:S]")],
    )

    texts = _texts(MinimalAgentPipeline().build_prompt_messages(state, "s"))

    assert texts[-1] == "Kept. [cite:L:7:13:::C:S]"


def test_narration_between_tool_calls_is_sent_without_markers():
    from tests.test_agent_intermediate_messages import (  # pylint: disable=import-outside-toplevel
        ScriptedModel,
        answer,
        make_state,
        tool_turn,
    )

    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.chat_mode = IrisChatMode.COURSE
    sent = []
    callback = SimpleNamespace(send_intermediate=sent.append)
    model = ScriptedModel(
        [
            tool_turn(
                "Slide 13 says parts die with the whole. [src:1] Let me check the FAQ."
            ),
            answer("Final. [src:1]"),
        ]
    )

    output = pipeline._run_agent_loop(make_state(callback, model))

    assert sent == ["Slide 13 says parts die with the whole. Let me check the FAQ."]
    # The final answer keeps its markers; they become cite blocks afterwards.
    assert output == "Final. [src:1]"


def test_strip_source_markers_keeps_code():
    assert (
        strip_source_markers("A. [src:1] `b[src:2]` [cite:F:1::::k:s]")
        == "A. `b[src:2]`"
    )


# --------------------------------------------------------------------------- language, MCQ


def test_markers_do_not_count_as_prose_for_the_answer_language():
    markers = " ".join(f"[src:{n}]" for n in range(1, 9))
    # Too short to tell on its own; the letters of the markers must not change that.
    assert detect_language_name(f"Ja, genau so ist es. {markers}") is None
    german = (
        "Bei der Komposition gehört das Teil genau zu einem Ganzen und wird mit ihm "
        "gelöscht. "
    )
    assert reply_language(f"{german}{markers}", None, [], "en") == "German"
    english = "With composition, the part belongs to exactly one whole and is deleted with it. "
    assert reply_language(f"{english}{markers}", None, [], "de") == "English"


@pytest.mark.parametrize("mcq_type", ["mcq", "mcq-set"])
def test_mcq_fields_lose_source_markers(mcq_type):
    question = {
        "question": "What dies with the whole? [src:1]",
        "options": [
            {"text": "The part [src:2]", "correct": True},
            {"text": "Nothing [src:3", "correct": False},
        ],
        "explanation": "Composition. [src:1] [cite:L:7:13:::C:S]",
    }
    payload = (
        {"type": "mcq", **question}
        if mcq_type == "mcq"
        else {"type": "mcq-set", "questions": [question]}
    )

    cleaned = json.loads(_strip_stray_citations(json.dumps(payload)))

    q = cleaned if mcq_type == "mcq" else cleaned["questions"][0]
    assert q["question"] == "What dies with the whole?"
    assert [o["text"] for o in q["options"]] == ["The part", "Nothing"]
    assert q["explanation"] == "Composition."


def test_mcq_fields_keep_code_that_looks_like_a_marker():
    payload = {
        "type": "mcq",
        "question": "What does `values[src:dst]` return? [src:1]",
        "options": [{"text": "A copy of `values[src:dst]`", "correct": True}],
        "explanation": "```python\nvalues[src:dst]\n```\nSlicing copies. [src:1]",
    }

    cleaned = json.loads(_strip_stray_citations(json.dumps(payload)))

    assert cleaned["question"] == "What does `values[src:dst]` return?"
    assert cleaned["options"][0]["text"] == "A copy of `values[src:dst]`"
    assert cleaned["explanation"] == "```python\nvalues[src:dst]\n```\nSlicing copies."


# --------------------------------------------------------------------------- prompts, config


def test_system_prompt_explains_markers_only_when_a_source_tool_exists():
    context = _base_context()
    assert "[src:" not in _render_template("chat_system_prompt.j2", context)

    for tool in ("allow_lecture_tool", "allow_faq_tool"):
        with_tool = dict(context, **{tool: True})
        assert "## Citing Sources" in _render_template(
            "chat_system_prompt.j2", with_tool
        )


@pytest.mark.parametrize("support_level", ["low", "moderate", "high"])
def test_guide_keeps_markers_with_the_content_they_belong_to(support_level):
    prompt = _render_template(
        "exercise_chat_guide_prompt.j2",
        {"problem_statement": "Implement a heap.", "support_level": support_level},
    )

    assert "Keep a marker next to the content it belongs to" in prompt
    assert "never add new markers" in prompt


def test_chat_variants_resolve_with_the_reduced_citation_config():
    variants = ChatPipeline.get_variants()

    assert {variant.id for variant in variants} == {"default", "advanced"}


def test_chat_variants_resolve_with_the_old_citation_config(monkeypatch):
    """Servers keep the old citation chat roles until their config is edited by hand."""
    llm_configuration = copy.deepcopy(iris_settings.llm_configuration)
    citation = llm_configuration["citation_pipeline"]
    citation["default"]["chat"] = dict(citation["default"]["keyword_summary"])
    citation["advanced"] = {"chat": dict(citation["default"]["keyword_summary"])}
    monkeypatch.setattr(iris_settings, "llm_configuration", llm_configuration)

    validate_llm_configuration()
    variants = ChatPipeline.get_variants()

    assert {variant.id for variant in variants} == {"default", "advanced"}


def test_example_config_labels_citations_locally_without_thinking():
    citation = iris_settings.llm_configuration["citation_pipeline"]

    assert set(citation) == {"default"}
    assert citation["default"]["keyword_summary"]["local"] == "qwen3.8-27b-nothink"


# --------------------------------------------------------------------------- run lifecycle


def test_a_source_from_before_a_switch_stays_citable():
    """Retrieval in lecture A, switch to B, retrieval in B: both sources can be cited."""
    state = _lecture_chat_state(
        _dto(
            chat_mode=IrisChatMode.LECTURE,
            lecture=PyrisLectureDTO(id=41),
            lectures=_lectures(),
        )
    )
    state.citation_sources = CitationSourceRegistry()
    contents = iter(
        [
            LectureRetrievalDTO(
                lecture_unit_segments=[],
                lecture_transcriptions=[],
                lecture_unit_page_chunks=[_page_chunk("Lecture A slide", page=3)],
            ),
            LectureRetrievalDTO(
                lecture_unit_segments=[],
                lecture_transcriptions=[],
                lecture_unit_page_chunks=[_page_chunk("Lecture B slide", page=9)],
            ),
        ]
    )
    state.lecture_retriever = lambda **kwargs: next(contents)
    retrieval = provide_lecture_retrieval(state)
    switch = provide_switch_chat_context(state)

    first = retrieval("composition")
    switch("LECTURE_CHAT", 42)
    second = retrieval("composition")

    assert "Source id: [src:1]" in first and "Source id: [src:2]" in second
    result = render_citations("A [src:1]. B [src:2].", state.citation_sources)
    assert result == "A [cite:L:7:3::::]. B [cite:L:7:9::::]."


def _guide_state(answer):
    state = SimpleNamespace(
        result=answer,
        pending_context_switch=None,
        dto=SimpleNamespace(
            settings=None, programming_exercise=None, text_exercise=None
        ),
    )
    return state


@pytest.mark.parametrize(
    "guide_output, expected",
    [
        ("!ok!", "Parts die. [cite:L:7:13:::K:S]\n```java\nnew Room();\n```"),
        (
            "Parts die. [src:1]\n```java\nnew Space();\n```",
            "Parts die. [cite:L:7:13:::K:S]\n```java\nnew Space();\n```",
        ),
        ("What happens to a room when its building is torn down?", None),
    ],
)
def test_guide_outcomes_keep_only_the_markers_of_kept_content(guide_output, expected):
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.chat_mode = IrisChatMode.EXERCISE
    pipeline._create_partial_result_sender = lambda state: None
    pipeline._run_guide_refinement = lambda state, response, stream_handler=None: (
        guide_output,
        response if guide_output == "!ok!" else guide_output,
    )
    state = _guide_state("Parts die. [src:1]\n```java\nnew Room();\n```")

    refined = pipeline._refine_response(state)
    rendered = render_citations(refined, _registry_with_sources(), {1: ("K", "S")})

    if expected is None:
        assert rendered == guide_output
    else:
        assert rendered == expected


def test_exercise_guide_drafts_use_the_citation_free_transform():
    pipeline = ChatPipeline.__new__(ChatPipeline)
    state = SimpleNamespace(
        dto=SimpleNamespace(
            settings=SimpleNamespace(
                stream_response=True, authentication_token=CallbackToken("token")
            )
        ),
        callback=SimpleNamespace(url="http://x", run_id="run"),
    )

    sender = pipeline._create_partial_result_sender(state)

    assert sender._text_transform is citation_free_draft


# --------------------------------------------------------------------------- MCQ insertion paths


_MCQ_WITH_MARKERS = {
    "type": "mcq",
    "question": "What dies with the whole? [src:1]",
    "options": [
        {"text": "The part [src:2]", "correct": True},
        {"text": "Nothing", "correct": False},
    ],
    "explanation": "Composition. [src:1]",
}


def _assert_mcq_clean(result):
    assert "[src" not in result
    assert "What dies with the whole?" in result and "The part" in result


def test_mcq_tool_path_inserts_clean_json():
    state = SimpleNamespace(
        mcq_parallel=False,
        result="Here is a question:\n[MCQ_RESULT]",
        mcq_result_storage={"mcq_json": json.dumps(_MCQ_WITH_MARKERS)},
    )
    mcq_post_agent_hook(state, SimpleNamespace(tokens=[]), lambda state, token: None)

    _assert_mcq_clean(state.result)


@pytest.mark.parametrize("count", [1, 3])
def test_mcq_parallel_paths_insert_clean_json(count):
    queue = Queue()
    for _ in range(count):
        queue.put(("mcq", json.dumps(_MCQ_WITH_MARKERS)))
    state = SimpleNamespace(
        mcq_parallel=True,
        mcq_count=count,
        mcq_thread=SimpleNamespace(
            join=lambda timeout=None: None, is_alive=lambda: False
        ),
        result="Here you go.",
        mcq_result_storage={"queue": queue},
    )
    mcq_post_agent_hook(state, SimpleNamespace(tokens=[]), lambda state, token: None)

    _assert_mcq_clean(state.result)
    assert ('"mcq-set"' in state.result) == (count > 1)

"""The summary shown with a citation must say what the cited source says, nothing more.

A small model writes the keyword and summary of every cited source from the source alone
(``citation_label_prompt.txt``). For a slide with a definition and the data of an example
but no outcome, it drew its own conclusion, and the summary then read as if the slide said it.
The unit tests guard the prompt and what the model receives, not the model's behavior.
"""

import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

# Bootstrap the iris package (see test_chat_latency_ordering.py for the circular import).
import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.domain.retrieval.lecture.lecture_retrieval_dto import (  # noqa: E402
    LectureUnitPageChunkRetrievalDTO,
)
from iris.llm.structured_output import parse_structured_output  # noqa: E402
from iris.pipeline.shared import citation_pipeline  # noqa: E402
from iris.pipeline.shared.citation_pipeline import CitationPipeline  # noqa: E402
from iris.pipeline.shared.citation_sources import CitationSourceRegistry  # noqa: E402

PROMPT_PATH = (
    Path(citation_pipeline.__file__).parents[1]
    / "prompts"
    / "citation_label_prompt.txt"
)
RULE = "Describe only what the source itself contains"
PARAGRAPH = (
    "A concurrent history is linearizable if operations can be ordered as legal "
    "sequential operations while preserving real-time order. History H: W.write(1) "
    "invoked at 1, R.read() invoked at 2, W returns at 3, R returns 0 at 4."
)
SUMMARY = "Defines linearizability and gives an example history of a write and a read"


def _slide_registry() -> CitationSourceRegistry:
    registry = CitationSourceRegistry()
    registry.register_page_chunk(
        LectureUnitPageChunkRetrievalDTO(
            uuid=str(uuid4()),
            course_id=1,
            course_name="Distributed Systems",
            course_description="",
            lecture_id=4,
            lecture_name="Consistency",
            lecture_unit_id=7,
            lecture_unit_name="Linearizability",
            lecture_unit_link="",
            course_language="en",
            page_number=12,
            display_page_number=13,
            page_text_content=PARAGRAPH,
            base_url="",
        )
    )
    return registry


class _RecordingLlm:
    """Stands in for IrisChatModel and records the prompt the label call sends."""

    prompts: list = []

    def __init__(self, request_handler, completion_args):
        del request_handler, completion_args
        self.tokens = None

    def structured(self, messages, schema):
        _RecordingLlm.prompts.append(messages[0].contents[0].text_content)
        response = {"labels": [{"source": 1, "keyword": "Lin", "summary": SUMMARY}]}
        return parse_structured_output(schema, json.dumps(response))


def _flat(text: str) -> str:
    """The text with its line breaks and indents folded, so phrases survive rewrapping."""
    return " ".join(text.split())


def test_the_label_prompt_forbids_claims_the_source_does_not_state():
    prompt = _flat(PROMPT_PATH.read_text(encoding="utf-8"))

    assert RULE in prompt
    assert "even when its data would allow them" in prompt
    assert "describe an example without an outcome as that example" in prompt
    # The earlier rules of the summary stay.
    assert "do not state results the student may still be working out" in prompt
    assert "do not mention the source, slide or lecturer" in prompt


def test_the_label_prompt_still_formats_with_the_new_rule():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    rendered = prompt.format(language="German", sources="Source 1:\nText")

    assert RULE in _flat(rendered)
    assert '{"labels": [{"source": 3, "keyword": "...", "summary": "..."}]}' in rendered
    assert rendered.rstrip().endswith("Source 1:\nText")


def test_the_label_model_receives_the_rule_the_language_and_the_source():
    _RecordingLlm.prompts = []
    with (
        patch.object(citation_pipeline, "resolve_model", return_value="m"),
        patch.object(citation_pipeline, "LlmRequestHandler"),
        patch.object(citation_pipeline, "IrisChatModel", _RecordingLlm),
    ):
        pipeline = CitationPipeline(local=True)
        result = pipeline(
            "The read may see the old value. [src:1]",
            _slide_registry(),
            language="English",
        )

    assert len(_RecordingLlm.prompts) == 1
    sent = _RecordingLlm.prompts[0]
    assert RULE in _flat(sent)
    assert "write keywords and summaries in English" in sent
    assert f"Source 1:\n{PARAGRAPH}" in sent
    assert result == f"The read may see the old value. [cite:L:7:12:::Lin:{SUMMARY}]"

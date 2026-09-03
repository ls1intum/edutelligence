"""Tests for inline citations.

The answer model writes short handles (``[cite:3]``) while it streams; the
registry expands them into the markers the client turns into bubbles. What
matters here is that the client never sees a broken or bogus marker, and that a
handle whose enrichment is still running simply appears a moment later instead
of holding the answer back.
"""

# pylint: skip-file

import threading
import time
from itertools import cycle
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

from iris.common.pipeline_enum import PipelineEnum
from iris.common.token_usage_dto import TokenUsageDTO
from iris.pipeline.shared.citation_registry import (
    CITE_TYPE_FAQ,
    CITE_TYPE_LECTURE,
    CitationEnricher,
    CitationRegistry,
)


class _StubEnricher:
    """Enricher whose calls can be released one at a time."""

    def __init__(self, gate: threading.Event | None = None):
        self.gate = gate
        self.keyword_calls: list[list[str]] = []
        self.summary_calls: list[str] = []
        self._counter = 0
        self._lock = threading.Lock()

    def generate_keyword(self, content, language_instruction, used_keywords):
        if self.gate is not None:
            self.gate.wait(timeout=5)
        with self._lock:
            self.keyword_calls.append(list(used_keywords))
            self._counter += 1
            keyword = f"Topic{self._counter}"
        return keyword, []

    def generate_summary(self, content, language_instruction):
        if self.gate is not None:
            self.gate.wait(timeout=5)
        self.summary_calls.append(content)
        return f"Summary of {content}", []


def _register_lecture(registry, page=7, content="Backpropagation explained"):
    return registry.register(
        CITE_TYPE_LECTURE, 42, content, page=page, dedup_key=f"chunk-{page}"
    )


def test_handle_expands_into_the_full_marker():
    registry = CitationRegistry(_StubEnricher())
    handle = _register_lecture(registry)
    assert handle == "[cite:1]"

    rendered = registry.render(f"Gradients flow backwards.{handle}", final=True)

    assert rendered == (
        "Gradients flow backwards."
        "[cite:L:42:7:::Topic1:Summary of Backpropagation explained]"
    )
    registry.close()


def test_faq_marker_leaves_page_and_timestamps_empty():
    registry = CitationRegistry(_StubEnricher())
    handle = registry.register(CITE_TYPE_FAQ, 9, "When is the exam? In March.")

    rendered = registry.render(f"The exam is in March.{handle}", final=True)

    assert rendered == (
        "The exam is in March."
        "[cite:F:9::::Topic1:Summary of When is the exam? In March.]"
    )
    registry.close()


def test_invented_handle_is_dropped():
    """A handle with no source behind it can never become a bubble."""
    registry = CitationRegistry(_StubEnricher())
    _register_lecture(registry)

    assert registry.render("Made up.[cite:99]", final=True) == "Made up."
    registry.close()


def test_pending_enrichment_is_hidden_in_partials_and_appears_later():
    gate = threading.Event()
    enricher = _StubEnricher(gate)
    registry = CitationRegistry(enricher)
    handle = _register_lecture(registry)

    # First partial: enrichment has just been kicked off and cannot be ready.
    assert registry.render(f"Gradients flow.{handle}") == "Gradients flow."

    gate.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        rendered = registry.render(f"Gradients flow.{handle}")
        if rendered != "Gradients flow.":
            break
    assert rendered == (
        "Gradients flow.[cite:L:42:7:::Topic1:Summary of Backpropagation explained]"
    )
    registry.close()


def test_final_render_waits_for_enrichment():
    gate = threading.Event()
    registry = CitationRegistry(_StubEnricher(gate))
    handle = _register_lecture(registry)
    rendered_holder = {}
    done = threading.Event()

    def run_render() -> None:
        rendered_holder["value"] = registry.render(
            f"Gradients flow.{handle}", final=True
        )
        done.set()

    thread = threading.Thread(target=run_render)
    thread.start()

    time.sleep(0.05)
    assert not done.is_set()

    gate.set()
    assert done.wait(timeout=5)
    thread.join(timeout=1)

    assert rendered_holder["value"] == (
        "Gradients flow.[cite:L:42:7:::Topic1:Summary of Backpropagation explained]"
    )
    registry.close()


def test_partially_typed_handle_is_hidden_until_complete():
    registry = CitationRegistry(_StubEnricher())
    _register_lecture(registry)

    # Every prefix the model can be in the middle of typing.
    for fragment in ("[", "[c", "[ci", "[cit", "[cite", "[cite:", "[cite:1"):
        assert registry.render(f"Gradients flow.{fragment}") == "Gradients flow."
    registry.close()


def test_final_render_keeps_unrelated_brackets():
    """Only citation-shaped text is touched; ordinary brackets survive."""
    registry = CitationRegistry(_StubEnricher())

    assert registry.render("Cost is 5 [USD]", final=True) == "Cost is 5 [USD]"
    assert registry.render("See [the docs](x)", final=True) == "See [the docs](x)"
    registry.close()


def test_same_source_registered_twice_shares_one_handle():
    """The viewed slide and the same chunk from RAG must not become two bubbles."""
    registry = CitationRegistry(_StubEnricher())

    first = registry.register(CITE_TYPE_LECTURE, 42, "Content", page=7, dedup_key="u-1")
    second = registry.register(
        CITE_TYPE_LECTURE, 42, "Content", page=7, dedup_key="u-1"
    )

    assert first == second == "[cite:1]"
    registry.close()


def test_registry_without_enricher_renders_empty_fields():
    """Pipelines that do not cite still render safely."""
    registry = CitationRegistry()
    handle = _register_lecture(registry)

    assert registry.render(f"Text.{handle}", final=True) == "Text.[cite:L:42:7::::]"
    registry.close()


class _FakeChatModel(GenericFakeChatModel):
    """Real Runnable so ``prompt | llm | StrOutputParser()`` works end to end."""

    tokens: TokenUsageDTO | None = None

    def __init__(self, request_handler=None, completion_args=None, **kwargs):
        del request_handler, completion_args
        super().__init__(messages=cycle(["  Backpropagation  "]), **kwargs)
        # IrisLangchainChatModel records the usage of its last call here as a
        # single DTO -- not a list, and None when nothing was reported.
        self.tokens = TokenUsageDTO(
            model_info="nano", numInputTokens=10, numOutputTokens=2
        )


def _make_enricher() -> CitationEnricher:
    with (
        patch("iris.pipeline.shared.citation_registry.resolve_model", return_value="m"),
        patch("iris.pipeline.shared.citation_registry.LlmRequestHandler"),
    ):
        return CitationEnricher()


def test_enrichment_reaches_the_rendered_marker_through_the_real_enricher():
    """End-to-end over the real enricher: the marker must not stay empty."""
    enricher = _make_enricher()
    registry = CitationRegistry(enricher)
    handle = _register_lecture(registry)

    with patch(
        "iris.pipeline.shared.citation_registry.IrisLangchainChatModel",
        _FakeChatModel,
    ):
        rendered = registry.render(f"Gradients flow.{handle}", final=True)

    assert rendered == (
        "Gradients flow.[cite:L:42:7:::Backpropagation:Backpropagation]"
    )
    assert registry.tokens and all(
        token.pipeline == PipelineEnum.IRIS_CITATION_PIPELINE
        for token in registry.tokens
    )
    registry.close()

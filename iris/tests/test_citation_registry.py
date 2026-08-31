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

from iris.pipeline.shared.citation_registry import (
    CITE_TYPE_FAQ,
    CITE_TYPE_LECTURE,
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


def test_final_render_falls_back_to_empty_fields_when_enrichment_never_finishes():
    """The answer must not be held hostage by a hanging enrichment call."""
    gate = threading.Event()  # never set
    registry = CitationRegistry(_StubEnricher(gate))
    handle = _register_lecture(registry)

    import iris.pipeline.shared.citation_registry as module

    original = module.FINAL_ENRICHMENT_TIMEOUT_SECONDS
    module.FINAL_ENRICHMENT_TIMEOUT_SECONDS = 0.05
    try:
        rendered = registry.render(f"Gradients flow.{handle}", final=True)
    finally:
        module.FINAL_ENRICHMENT_TIMEOUT_SECONDS = original
        gate.set()

    assert rendered == "Gradients flow.[cite:L:42:7::::]"
    registry.close()


def test_partially_typed_handle_is_hidden_until_complete():
    registry = CitationRegistry(_StubEnricher())
    _register_lecture(registry)

    # Every prefix the model can be in the middle of typing.
    for fragment in ("[", "[c", "[ci", "[cit", "[cite", "[cite:", "[cite:1"):
        assert registry.render(f"Gradients flow.{fragment}") == "Gradients flow."
    registry.close()


def test_final_render_keeps_an_unterminated_fragment():
    """Truncation is a streaming concern; the final answer is verbatim."""
    registry = CitationRegistry(_StubEnricher())

    assert registry.render("Cost is 5 [USD", final=True) == "Cost is 5 [USD"
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


def test_keywords_are_generated_sequentially_so_they_stay_unique():
    enricher = _StubEnricher()
    registry = CitationRegistry(enricher)
    first = registry.register(CITE_TYPE_LECTURE, 42, "First topic", page=1)
    second = registry.register(CITE_TYPE_LECTURE, 42, "Second topic", page=2)

    rendered = registry.render(f"A{first} B{second}", final=True)

    assert "Topic1" in rendered and "Topic2" in rendered
    # The second keyword call must know about the first one's result, which only
    # holds if the calls do not run concurrently.
    assert enricher.keyword_calls == [[], ["Topic1"]]
    registry.close()


def test_enrichment_runs_once_per_handle_however_often_it_is_rendered():
    """render() is called on every partial; that must not fan out into calls."""
    registry = CitationRegistry(_StubEnricher())
    handle = _register_lecture(registry)

    for _ in range(5):
        registry.render(f"Gradients flow.{handle}")
    registry.render(f"Gradients flow.{handle}", final=True)

    assert len(registry._summary_futures) == 1
    registry.close()


def test_registry_without_enricher_renders_empty_fields():
    """Pipelines that do not cite still render safely."""
    registry = CitationRegistry()
    handle = _register_lecture(registry)

    assert registry.render(f"Text.{handle}", final=True) == "Text.[cite:L:42:7::::]"
    registry.close()


def test_close_is_idempotent():
    registry = CitationRegistry(_StubEnricher())
    _register_lecture(registry)
    registry.close()
    registry.close()

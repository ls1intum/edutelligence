"""The summary shown with a citation must say what the cited paragraph says, nothing more.

The summary is written by a small model from the cited paragraph alone. Asked only for a content
summary it drew its own conclusion from the data of an example, here the verdict on a history that
the slide never states, and the text then read as if the slide said it.
"""

# pylint: disable=protected-access

import threading
from pathlib import Path
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

# Bootstrap the iris package (see test_chat_latency_ordering.py for the circular import).
import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.pipeline.shared import citation_pipeline  # noqa: E402
from iris.pipeline.shared.citation_pipeline import CitationPipeline  # noqa: E402

PROMPTS = Path(citation_pipeline.__file__).parents[1] / "prompts"
PARAGRAPH = (
    "A concurrent history is linearizable if operations can be ordered as legal "
    "sequential operations while preserving real-time order. History H: W.write(1) "
    "invoked at 1, R.read() invoked at 2, W returns at 3, R returns 0 at 4."
)


def test_the_summary_prompt_forbids_conclusions_the_paragraph_does_not_state():
    prompt = (PROMPTS / "citation_summary_prompt.txt").read_text(encoding="utf-8")

    assert "{Paragraph}" in prompt
    assert "Summarize only what the paragraph itself states" in prompt
    assert "verdicts" in prompt and "even when the data in it would allow" in prompt
    assert "Do NOT include" in prompt  # the rules for the citation block stay


def test_the_model_receives_the_rule_and_the_paragraph(monkeypatch):
    sent = []

    def fake_model(**_kwargs):
        def respond(prompt_value):
            sent.append(prompt_value.to_string())
            return AIMessage(content="An example history with a write and a read.")

        model = RunnableLambda(respond)
        model.tokens = None
        return model

    monkeypatch.setattr(citation_pipeline, "IrisLangchainChatModel", fake_model)
    pipeline = CitationPipeline.__new__(CitationPipeline)
    pipeline._keyword_summary_request_handler = MagicMock()
    pipeline._keyword_summary_completion_args = MagicMock()
    pipeline._append_tokens = MagicMock()
    pipeline._tokens_lock = threading.Lock()
    pipeline._last_citation_content_by_seq = {1: PARAGRAPH}
    pipeline.summary_prompt_str = (PROMPTS / "citation_summary_prompt.txt").read_text(
        encoding="utf-8"
    )

    summary = pipeline._generate_single_summary(
        "Format all citations in English.\n\n", 1
    )

    assert summary == "An example history with a write and a read."
    assert len(sent) == 1
    assert sent[0].startswith("Format all citations in English.")
    assert "Summarize only what the paragraph itself states" in sent[0]
    assert PARAGRAPH in sent[0]

from types import SimpleNamespace
from unittest.mock import MagicMock

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.pipeline.rewriting_pipeline import RewritingPipeline  # noqa: E402


def _pipeline_answering(text: str) -> RewritingPipeline:
    pipeline = RewritingPipeline.__new__(RewritingPipeline)
    pipeline.consistency_handler = MagicMock()
    pipeline.consistency_handler.chat.return_value = SimpleNamespace(
        token_usage=None,
        contents=[SimpleNamespace(text_content=text)],
    )
    pipeline._append_tokens = MagicMock()  # pylint: disable=protected-access
    return pipeline


def test_fenced_json_after_leading_whitespace_is_parsed():
    # Qwen3 answers start with "\n\n" after the reasoning block.
    pipeline = _pipeline_answering(
        '\n\n```json\n{"type": "consistent", "message": "ok"}\n```'
    )
    result = pipeline.check_faq_consistency(
        [{"properties": {"question_title": "q", "question_answer": "a"}}], "final"
    )
    assert result == {"type": "consistent", "message": "ok"}

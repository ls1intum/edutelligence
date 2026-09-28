from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.llm.external.model import RerankResponse
from iris.llm.external.passthrough_reranker import PassthroughReranker
from iris.llm.llm_manager import LlmList
from iris.llm.request_handler.rerank_request_handler import RerankRequestHandler


def _passthrough_reranker() -> PassthroughReranker:
    return PassthroughReranker(
        id="passthrough-reranker",
        type="passthrough_reranker",
    )


def test_passthrough_reranker_is_a_valid_llm_config_entry():
    parsed = LlmList.model_validate(
        {
            "llms": [
                {
                    "id": "passthrough-reranker",
                    "type": "passthrough_reranker",
                    "model": "passthrough",
                }
            ]
        }
    )

    assert isinstance(parsed.llms[0], PassthroughReranker)


def test_passthrough_reranker_preserves_order_and_filters_invalid_documents():
    first = SimpleNamespace(content="first")
    missing_content = SimpleNamespace(content=None)
    second = SimpleNamespace(content="second")
    third = SimpleNamespace(content="third")
    manager = MagicMock()
    manager.get_llm_by_id.return_value = _passthrough_reranker()

    with patch(
        "iris.llm.request_handler.rerank_request_handler.LlmManager",
        return_value=manager,
    ):
        handler = RerankRequestHandler("passthrough-reranker")

    result = handler.rerank(
        query="query",
        documents=[first, None, missing_content, second, third],
        top_n=2,
        content_field_name="content",
    )

    assert result == [first, second]
    manager.get_llm_by_id.assert_called_once_with("passthrough-reranker")


def test_passthrough_reranker_handles_zero_and_oversized_limits():
    reranker = _passthrough_reranker()

    zero_result = reranker.rerank("query", ["a", "b"], top_n=0)
    assert zero_result == []  # pylint: disable=use-implicit-booleaness-not-comparison
    assert reranker.rerank("query", ["a", "b"], top_n=10) == [0, 1]


def test_existing_provider_reranker_path_is_unchanged():
    first = SimpleNamespace(content="first")
    second = SimpleNamespace(content="second")
    provider = MagicMock()
    provider.rerank.return_value = RerankResponse(
        results=[
            {"index": 1, "relevance_score": 0.9},
            {"index": 0, "relevance_score": 0.5},
        ]
    )
    manager = MagicMock()
    manager.get_llm_by_id.return_value = provider

    with patch(
        "iris.llm.request_handler.rerank_request_handler.LlmManager",
        return_value=manager,
    ):
        handler = RerankRequestHandler("provider-reranker")

    result = handler.rerank(
        query="query",
        documents=[first, second],
        top_n=2,
        content_field_name="content",
    )

    assert result == [second, first]
    provider.rerank.assert_called_once_with(
        query="query", documents=["first", "second"], top_n=2
    )

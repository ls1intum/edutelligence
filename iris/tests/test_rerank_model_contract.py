"""Unit tests for the shared reranker contract.

Rerankers are selected by config role (see the reranker roles resolved in
lecture_global_search_retrieval), so Cohere and a vLLM-served cross-encoder
must be interchangeable at the call site. Before RerankResponse existed each
client returned its provider's own object and RerankRequestHandler unpacked
that positionally (`_, results, _ =`), which only worked because Cohere's
response happens to have exactly three fields — any other reranker raised, and
the handler's except-clause turned that into a permanent process-wide disable.
"""

# pylint: skip-file

import httpx
import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.llm.external.model import RerankModel, RerankResponse  # noqa: E402
from iris.llm.external.vllm_rerank import (  # noqa: E402
    DEFAULT_RERANK_INSTRUCTION,
    VllmRerankModel,
)
from iris.llm.request_handler.rerank_request_handler import (  # noqa: E402
    RerankRequestHandler,
)


def _model(**overrides) -> VllmRerankModel:
    return VllmRerankModel(
        type="vllm_rerank",
        id="cloud-qwen3-reranker-8b",
        model="Qwen/Qwen3-Reranker-8B",
        base_url="https://logos.example/v1",
        api_key="dummy",  # pragma: allowlist secret
        **overrides,
    )


def _respond_with(model: VllmRerankModel, payload: dict) -> None:
    """Stub the client's transport so no network call is made."""
    model._client.post = lambda path, json: httpx.Response(  # noqa: SLF001
        200, json=payload, request=httpx.Request("POST", "https://logos.example/v1")
    )


def test_vllm_client_satisfies_the_rerank_contract():
    assert isinstance(_model(), RerankModel)


def test_relevance_score_field_is_normalised():
    model = _model()
    _respond_with(
        model, {"results": [{"index": 1, "relevance_score": 0.97}, {"index": 0}]}
    )
    with pytest.raises(ValueError):
        # Second item has no score at all, so the whole response is rejected.
        model.rerank(query="q", documents=["a", "b"], top_n=2)


def test_score_field_alias_is_accepted():
    # Some vLLM builds emit `score` rather than Cohere/Jina's `relevance_score`.
    model = _model()
    _respond_with(model, {"results": [{"index": 0, "score": 0.42}]})
    response = model.rerank(query="q", documents=["a"], top_n=1)
    assert isinstance(response, RerankResponse)
    assert response.results[0].relevance_score == pytest.approx(0.42)


def test_unknown_score_field_raises_instead_of_scoring_zero():
    # A silent 0.0 would fall under the relevance gate for every candidate and
    # surface as a confident "no content exists" empty state.
    model = _model()
    _respond_with(model, {"results": [{"index": 0, "confidence": 0.9}]})
    with pytest.raises(ValueError, match="no known score field"):
        model.rerank(query="q", documents=["a"], top_n=1)


def test_empty_results_are_not_an_error():
    model = _model()
    _respond_with(model, {"results": []})
    assert model.rerank(query="q", documents=["a"], top_n=1).results == []


def test_instruction_fold_is_off_by_default():
    # The Logos reranker chat template supplies the instruction server-side;
    # folding a second one client-side depresses scores.
    assert _model()._format_query("what is NMS") == "what is NMS"


def test_instruction_fold_applies_when_configured():
    model = _model(instruction=DEFAULT_RERANK_INSTRUCTION)
    folded = model._format_query("what is NMS")
    assert folded.startswith(DEFAULT_RERANK_INSTRUCTION)
    assert folded.endswith("Query: what is NMS")


def test_api_key_is_not_leaked_in_str():
    # RerankModel's NotImplementedError and the retrieval logs interpolate
    # str(model), so __str__ must stay key-free. (Pydantic's __repr__ still
    # renders every field, exactly as it does for the Cohere client.)
    assert "dummy" not in str(_model())


class _StubReranker:
    """Any reranker that is not Cohere: a single-field RerankResponse."""

    def rerank(self, query, documents, top_n):
        return RerankResponse(
            results=[
                {"index": 2, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.5},
            ]
        )


class _Doc:
    def __init__(self, text: str):
        self.text = text


def test_request_handler_reorders_documents_for_a_non_cohere_reranker():
    documents = [_Doc("a"), _Doc("b"), _Doc("c")]
    handler = RerankRequestHandler.model_construct(
        model_id="cloud-qwen3-reranker-8b",
        llm_manager=type(
            "_Manager", (), {"get_llm_by_id": lambda self, _id: _StubReranker()}
        )(),
    )

    ranked = handler.rerank(
        query="q", documents=documents, top_n=2, content_field_name="text"
    )

    assert ranked == [documents[2], documents[0]]


def test_request_handler_skips_documents_missing_the_content_field():
    handler = RerankRequestHandler.model_construct(
        model_id="cloud-qwen3-reranker-8b", llm_manager=None
    )
    assert handler.rerank("q", [], top_n=2, content_field_name="text") == []

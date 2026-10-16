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
from iris.llm.request_handler import rerank_request_handler  # noqa: E402
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
    # A non-empty list with one document missing "text": the empty-list early return
    # (`if not documents`) cannot fire here, so this actually exercises the filter
    # comprehension rather than a branch above it.
    documents = [_Doc("valid text"), _Doc(None)]
    received_documents = []
    handler = RerankRequestHandler.model_construct(
        model_id="cloud-qwen3-reranker-8b",
        llm_manager=type(
            "_Manager",
            (),
            {
                "get_llm_by_id": lambda self, _id: type(
                    "_OneDocReranker",
                    (),
                    {
                        "rerank": lambda self, query, documents, top_n: (
                            received_documents.append(documents),
                            RerankResponse(
                                results=[{"index": 0, "relevance_score": 1.0}]
                            ),
                        )[1]
                    },
                )()
            },
        )(),
    )

    ranked = handler.rerank("q", documents, top_n=2, content_field_name="text")

    # Only the valid document's content ever reaches the reranker; the one missing
    # "text" was filtered out before the call, not passed through as empty content.
    # (Asserting only `ranked == [documents[0]]` would also pass if filtering were
    # skipped entirely, since the stub always returns index 0 regardless of input.)
    assert received_documents == [["valid text"]]
    assert ranked == [documents[0]]


def test_request_handler_missing_content_field_alone_returns_empty():
    handler = RerankRequestHandler.model_construct(
        model_id="cloud-qwen3-reranker-8b", llm_manager=None
    )
    assert handler.rerank("q", [_Doc(None)], top_n=2, content_field_name="text") == []


def test_request_handler_degrades_gracefully_when_the_model_id_is_not_configured():
    # get_llm_by_id returns None (no matching entry) rather than raising — a typo'd
    # id, or an entry commented out of llm_config.local.yml, which is exactly what
    # happened on this branch until it was manually uncommented for testing.
    handler = RerankRequestHandler.model_construct(
        model_id="not-a-configured-model",
        llm_manager=type("_Manager", (), {"get_llm_by_id": lambda self, _id: None})(),
    )
    documents = [_Doc("a"), _Doc("b"), _Doc("c")]

    ranked = handler.rerank("q", documents, top_n=2, content_field_name="text")

    assert ranked == documents[:2]
    # A missing config entry is permanent, not the transient failure the cooldown
    # exists to back off from; it must not start a cooldown for this model_id.
    assert not rerank_request_handler._in_cooldown("not-a-configured-model")


def test_missing_model_id_does_not_disable_a_different_working_reranker():
    rerank_request_handler.reset_rerank_cooldowns()  # isolate from other tests' state
    missing = RerankRequestHandler.model_construct(
        model_id="not-a-configured-model",
        llm_manager=type("_Manager", (), {"get_llm_by_id": lambda self, _id: None})(),
    )
    missing.rerank("q", [_Doc("a")], top_n=1, content_field_name="text")

    working = RerankRequestHandler.model_construct(
        model_id="a-working-model",
        llm_manager=type(
            "_Manager",
            (),
            {"get_llm_by_id": lambda self, _id: _StubReranker()},
        )(),
    )
    documents = [_Doc("a"), _Doc("b"), _Doc("c")]

    ranked = working.rerank("q", documents, top_n=2, content_field_name="text")

    # _StubReranker's fixed response (index 2 then 0) proves the real reranker path
    # ran, rather than the unranked fallback the missing-model handler would have
    # left every subsequent handler stuck on if the class-wide flag had flipped.
    assert ranked == [documents[2], documents[0]]


class _FailingReranker:
    def rerank(self, query, documents, top_n):
        raise RuntimeError("service unavailable")


def test_failure_starts_a_cooldown_for_that_model_only_and_it_expires(monkeypatch):
    rerank_request_handler.reset_rerank_cooldowns()
    failing = RerankRequestHandler.model_construct(
        model_id="flaky-model",
        llm_manager=type(
            "_Manager", (), {"get_llm_by_id": lambda self, _id: _FailingReranker()}
        )(),
    )
    working = RerankRequestHandler.model_construct(
        model_id="a-working-model",
        llm_manager=type(
            "_Manager", (), {"get_llm_by_id": lambda self, _id: _StubReranker()}
        )(),
    )
    documents = [_Doc("a"), _Doc("b"), _Doc("c")]

    assert failing.rerank("q", documents, top_n=2, content_field_name="text") == (
        documents[:2]
    )
    assert rerank_request_handler._in_cooldown("flaky-model")
    # Another reranker keeps working while the flaky one cools down.
    assert working.rerank("q", documents, top_n=2, content_field_name="text") == [
        documents[2],
        documents[0],
    ]

    # Once the cooldown has passed, the reranker is tried again.
    clock = [0.0]
    monkeypatch.setattr(rerank_request_handler.time, "monotonic", lambda: clock[0])
    rerank_request_handler.reset_rerank_cooldowns()
    rerank_request_handler._start_cooldown("flaky-model")
    clock[0] = rerank_request_handler.RERANK_FAILURE_COOLDOWN_SECONDS + 1
    assert not rerank_request_handler._in_cooldown("flaky-model")
    rerank_request_handler.reset_rerank_cooldowns()

from typing import Any, Literal

import httpx
from pydantic import ConfigDict

from iris.tracing import observe

from ...llm.external.model import RerankItem, RerankModel, RerankResponse

# Qwen3-Reranker is INSTRUCTION-AWARE: its relevance head judges "does this
# document satisfy this instruction + query?". That instruction is normally
# supplied by the reranker CHAT TEMPLATE that vLLM applies server-side. Logos
# deployed that template on the Qwen3-Reranker-8B lane on 2026-08-13
# (`--chat-template .../qwen3_reranker.jinja`), which restored native-quality
# score separation on /rerank (verified live: off-topic passages drop to ~0.00,
# direct answers ~0.99 — a thresholdable gate again).
#
# With the server supplying the instruction, folding a SECOND instruction into
# the query client-side double-instructs and DEPRESSES scores. Measured on real
# lecture retrieval (NMS query, 25 candidates): raw query top 0.996 / 11 kept at
# the 0.30 gate vs folded 0.979 / only 6 kept. So the default is now NO client
# fold (raw query). The fold is retained ONLY as an escape hatch for a gateway
# that does not apply the reranker chat template: set `instruction` to the
# constant below, which reproduces the pre-template client-side fix (documents
# stay raw — the query-side-only asymmetry mirrors the Qwen3-Embedding
# retrieval instruction).
DEFAULT_RERANK_INSTRUCTION = (
    "Given a search query from a university student, retrieve lecture "
    "passages that answer the query"
)

# Score field names seen across gateways: Cohere and Jina emit `relevance_score`,
# some vLLM builds emit `score`. Anything else is a protocol mismatch we must not
# paper over — see the ValueError in `_read_score`.
_SCORE_FIELDS = ("relevance_score", "score")


class VllmRerankModel(RerankModel):
    """Reranker client for a vLLM-served cross-encoder (e.g. Qwen3-Reranker on
    the TUM Logos gateway) exposed over the Jina/Cohere-compatible ``/rerank``
    HTTP endpoint.

    Normalises to the shared :class:`RerankResponse`, so it is interchangeable
    with any other configured reranker. The Qwen3 instruction protocol is
    confined to this class — shared retrieval code stays reranker-agnostic and
    never risks prefixing a query meant for a different reranker.
    """

    type: Literal["vllm_rerank"]
    base_url: str
    api_key: str
    # Rerank route appended to base_url. Default assumes base_url already ends
    # in the version segment (e.g. .../v1), matching the OpenAI-compatible chat
    # and embedding entries on the same gateway, so this only adds "/rerank"
    # (verified live: POST https://logos.aet.cit.tum.de/v1/rerank -> 200; the
    # bare "/rerank" and "/v2/rerank" routes 405). Configurable because other
    # gateways version rerank differently.
    rerank_path: str = "/rerank"
    # Optional client-side instruction fold. Default None: the Logos reranker
    # chat template already supplies the instruction (see module comment), so a
    # client fold would double-instruct and depress scores. Set to
    # DEFAULT_RERANK_INSTRUCTION only for a gateway that does not apply the
    # reranker chat template.
    instruction: str | None = None
    request_timeout: float = 10.0
    # Persistent connection pool, mirroring the other external clients: a fresh
    # TLS handshake per call is pure overhead inside the caller's rerank budget.
    _client: httpx.Client
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def model_post_init(self, context) -> None:  # pylint: disable=unused-argument
        self._client = httpx.Client(
            base_url=self.base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=self.request_timeout,
        )

    def _format_query(self, query: str) -> str:
        """Fold the configured instruction into the query, or return it raw when
        no instruction is set (the default, since the server-side reranker chat
        template now supplies the instruction). See the module comment."""
        if not self.instruction:
            return query
        return f"{self.instruction}\n\nQuery: {query}"

    def _read_score(self, item: dict[str, Any]) -> float:
        """Read a document's score, raising when the gateway uses an unknown
        field name.

        Deliberately NOT defaulted to 0.0: callers gate on an absolute
        threshold, so a silent zero would drop every candidate and surface as a
        confident "no content exists" empty state instead of a broken reranker.
        """
        for field in _SCORE_FIELDS:
            if item.get(field) is not None:
                return float(item[field])
        raise ValueError(
            f"Rerank response from {self.model} carries no known score field "
            f"(expected one of {_SCORE_FIELDS}, got {sorted(item)})"
        )

    @observe(name="vLLM Rerank", as_type="span")
    def rerank(self, query: str, documents: list[str], top_n: int) -> RerankResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "query": self._format_query(query),
            "documents": list(documents),
            "top_n": top_n,
        }
        response = self._client.post(self.rerank_path, json=payload)
        response.raise_for_status()
        return RerankResponse(
            results=[
                RerankItem(
                    index=int(item["index"]), relevance_score=self._read_score(item)
                )
                for item in (response.json().get("results") or [])
            ]
        )

    def __str__(self) -> str:
        return f"VllmRerank('{self.model}')"

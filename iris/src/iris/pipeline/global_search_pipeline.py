import json
import re
import time

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from weaviate import WeaviateClient

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.domain.search.lecture_search_dto import (
    GlobalSearchResponseDTO,
    LectureSearchResultDTO,
)
from iris.domain.search.search_intent_dto import SearchIntent
from iris.llm import CompletionArguments, LlmRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.llm.llm_configuration import resolve_model
from iris.pipeline.prompts.global_search_prompts import answer_system_prompt
from iris.pipeline.shared.global_search_intent_classifier import (
    classify as classify_intent,
)
from iris.pipeline.sub_pipeline import SubPipeline
from iris.retrieval.lecture.lecture_global_search_retrieval import (
    LectureGlobalSearchRetrieval,
)
from iris.tracing import observe

logger = get_logger(__name__)

# The answer model sometimes duplicates the schema's used_sources field as a
# trailing plain-text line — either INSIDE an otherwise valid JSON answer string
# (observed in the UI as a literal "Used_sources: [1, 3]" under the answer) or
# at the end of its output when it drops the JSON envelope entirely. Matches
# variants like "Used_sources: [1, 3]" / "used sources [2]" at end of text.
_TRAILING_USED_SOURCES_RE = re.compile(
    r"\s*used[_ ]?sources\s*:?\s*\[(?P<indices>[^\]]*)\]\s*\.?\s*$",
    re.IGNORECASE,
)


def _try_parse_json(text: str) -> dict | None:
    """Parse text as a JSON object, retrying with LaTeX backslashes escaped.

    LaTeX commands (e.g. \\alpha, \\sum) are invalid JSON escape sequences, so
    the retry escapes any backslash not already part of a recognised JSON
    escape. Returns None unless the result is a dict.
    """
    for candidate in (text, re.sub(r'\\(?!["\\/])', r"\\\\", text)):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _location_label(source: LectureSearchResultDTO) -> str:
    """Human-readable slide/video position tag for the numbered context."""
    page = source.lecture_unit.page_number
    if page == -1:
        meta = source.lecture_unit.display_meta or "video"
        return f"Video @ {meta}"
    return f"Slide {page}"


def parse_answer_response(raw: str, num_sources: int) -> tuple[str | None, set[int]]:
    """Parse the answer LLM's raw output into (answer, used 0-based indices).

    Pure string logic, extracted for unit-testability: structured parsing
    with salvage paths, then the sanitize/suppress guards that decide what a
    student may actually see.
    """
    answer, used_indices = _extract_answer(raw, num_sources)
    answer = _sanitize_and_suppress(answer, used_indices)
    return answer, used_indices


def _extract_answer(raw: str, num_sources: int) -> tuple[str | None, set[int]]:
    """Structured parse with salvage paths, in order: markdown fences, JSON
    with LaTeX-backslash repair, embedded-JSON salvage, plain text with a
    trailing "Used_sources: [..]" line (recovering attribution), raw text
    with all sources as the last resort."""
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
    parsed = _try_parse_json(cleaned)
    if parsed is None:
        # Salvage: the JSON envelope may be embedded in surrounding prose.
        embedded = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if embedded:
            parsed = _try_parse_json(embedded.group())
            if parsed is not None:
                logger.info(
                    "[global-search] parse_salvaged=embedded_json raw_len=%d",
                    len(raw),
                )
    if parsed is not None:
        answer = parsed.get("answer")
        # Treat null, "" and non-string values as no answer.
        answer = answer if isinstance(answer, str) and answer else None
        if answer is None:
            logger.info("[global-search] outcome=llm_null_json raw=%r", raw[:300])
        raw_indices = parsed.get("used_sources")
        used_indices = {
            i - 1
            for i in (raw_indices if isinstance(raw_indices, list) else [])
            if isinstance(i, int) and i >= 1
        }
        return answer, used_indices

    # Plain-text output (the model dropped the JSON envelope). If it ends
    # with a schema-imitating "Used_sources: [..]" line, recover the
    # attribution from it and strip the line; otherwise attach all sources —
    # there is no way to tell which were used.
    match = _TRAILING_USED_SOURCES_RE.search(cleaned)
    if match:
        used_indices = {
            int(n) - 1 for n in re.findall(r"\d+", match.group("indices"))
        } - {-1}
        answer = cleaned[: match.start()].rstrip() or None
        logger.warning(
            "[global-search] outcome=parse_salvaged_text used=%d/%d raw=%r",
            len(used_indices),
            num_sources,
            raw[:300],
        )
        return answer, used_indices

    logger.warning(
        "[global-search] outcome=parse_failed raw_len=%d raw=%r — "
        "returning raw text as answer with all sources",
        len(raw),
        raw[:300],
    )
    return cleaned or None, set(range(num_sources))


_REFUSAL_RE = re.compile(
    r"not (covered|mentioned|discussed|found|available|provided|present|included)"
    r"|not (in|part of) the (course|lecture|material|content|slides)"
    r"|no (mention|reference|explanation|definition|description|information)"
    r"|does not (cover|mention|discuss|provide|include|contain|address)"
    r"|cannot (answer|find|provide|address)",
    re.IGNORECASE,
)

# Refusal suppression only fires on short answers, so legitimate answers that
# mention gaps ("X is covered, Y is not") are never eaten.
_REFUSAL_MAX_CHARS = 120


def _sanitize_and_suppress(answer: str | None, used_indices: set[int]) -> str | None:
    """Guards between the parsed answer and the student's screen."""
    # The model may write the used_sources line inside a correctly parsed
    # answer string (observed live in the UI). Strip it — it is schema
    # leakage, never content.
    if answer:
        sanitized = _TRAILING_USED_SOURCES_RE.sub("", answer).rstrip()
        if sanitized != answer:
            logger.info("[global-search] answer_sanitized=trailing_used_sources_line")
            answer = sanitized or None

    # Safety net: if the LLM ignored the null instruction and wrote a short
    # refusal instead of a grounded answer, suppress it so the client never
    # sees a "not covered" message.
    if answer and len(answer) < _REFUSAL_MAX_CHARS and _REFUSAL_RE.search(answer):
        logger.info(
            "[global-search] outcome=refusal_suppressed suppressed_answer=%r",
            answer,
        )
        answer = None

    # Grounding contract: an answer that cites no sources came from world
    # knowledge, not course content — never show it (observed live: a 4-char
    # "Yes."-style answer with used_sources=[]).
    if answer and not used_indices:
        logger.info(
            "[global-search] outcome=ungrounded_suppressed answer_len=%d "
            "suppressed_answer=%r",
            len(answer),
            answer[:200],
        )
        answer = None

    return answer


class GlobalSearchPipeline(SubPipeline):
    """
    Pipeline that answers a student's question from retrieved course content.

    Retrieval embeds the query with the Qwen3 retrieval instruction and lets a
    cross-encoder reranker order and gate the candidate pool; the answer LLM
    then grounds a concise answer on the surviving sources. (An earlier HyDE
    step was removed after a held-out ablation showed identical top sources,
    ~30% lower answer latency, and eliminated a model dependency that returned
    empty output on 35-50% of calls.)
    """

    answer_llm: IrisLangchainChatModel
    answer_pipeline: Runnable

    def __init__(self, client: WeaviateClient, local: bool = False):
        super().__init__(implementation_id="global_search_pipeline")
        self.tokens = []
        self.retriever = LectureGlobalSearchRetrieval(client, local=local)

        pipeline_id = "global_search_pipeline"
        answer_model = resolve_model(pipeline_id, "default", "answer", local=local)
        embedding_model = resolve_model(
            pipeline_id, "default", "embedding", local=local
        )
        logger.info(
            "Global search pipeline | mode=%s answer_llm=%s embedding=%s",
            "local" if local else "cloud",
            answer_model,
            embedding_model,
        )

        answer_completion_args = CompletionArguments(
            response_format="JSON", max_tokens=600
        )
        self.answer_llm = IrisLangchainChatModel(
            request_handler=LlmRequestHandler(model_id=answer_model),
            completion_args=answer_completion_args,
        )
        self.answer_pipeline = self.answer_llm | StrOutputParser()

        # The language directive sits at the END of the USER message, not only in
        # the system prompt: with German-heavy sources, gpt-5-mini at minimal
        # reasoning follows the context language over a mid-system-prompt rule
        # (observed live: English question, German answer). The final position is
        # the one light models weight most, and the model itself is the only
        # reliable language identifier for messy queries (typos, Arabizi,
        # code-switching) — no string-level detector handles those.
        self.answer_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", answer_system_prompt),
                (
                    "user",
                    "Course content:\n{context}\n\nQuestion: {query}\n\n"
                    "ANSWER LANGUAGE = the language of the question above. "
                    "The sources' language is irrelevant — translate what "
                    "you use into the question's language.",
                ),
            ]
        )

    @observe(name="Global Search Pipeline")
    def __call__(
        self, query: str, limit: int = 5, intent: SearchIntent | None = None, **_kwargs
    ) -> GlobalSearchResponseDTO:
        """
        Answer a student's question from retrieved course content.

        :param query: The student's question or search text.
        :param limit: Maximum number of source segments to retrieve.
        :param intent: Pre-computed intent (SearchIntent). If None,
                       the classifier is called here.
        :return: An answer with source references.
        """
        # Guard: skip the full LLM pipeline for navigation queries
        if intent is None:
            intent = classify_intent(query)
        logger.debug("Intent classification | query=%r intent=%s", query[:80], intent)
        if intent == SearchIntent.SKIP_AI:
            sources = self.retriever.search(query=query, limit=limit)
            return GlobalSearchResponseDTO(answer=None, sources=sources)

        sources = self._retrieve_sources(query, limit)
        if not sources:
            logger.info("[global-search] outcome=no_sources query=%r", query[:120])
            return GlobalSearchResponseDTO(answer=None, sources=[])

        grounded_sources = [s for s in sources if s.snippet]
        if not grounded_sources:
            logger.info(
                "[global-search] outcome=no_grounded_sources sources=%d query=%r",
                len(sources),
                query[:120],
            )
            return GlobalSearchResponseDTO(answer=None, sources=[])

        raw = self._generate_answer(query, grounded_sources)
        answer, used_indices = parse_answer_response(raw, len(grounded_sources))
        used_sources = [s for i, s in enumerate(grounded_sources) if i in used_indices]

        self._append_tokens(
            self.answer_llm.tokens, PipelineEnum.IRIS_GLOBAL_SEARCH_PIPELINE
        )

        if answer:
            logger.info(
                "[global-search] outcome=answered answer_len=%d used_sources=%d/%d",
                len(answer),
                len(used_sources),
                len(grounded_sources),
            )
        return GlobalSearchResponseDTO(answer=answer, sources=used_sources)

    def _retrieve_sources(self, query: str, limit: int) -> list[LectureSearchResultDTO]:
        """Candidate retrieval with the instruct query embedding.

        The reranker orders the pool on one calibrated scale and the
        threshold gates it — an all-below-threshold pool is the honest
        "no content exists" state and skips the answer LLM entirely. An empty
        pool can also mean the semantic lane missed named entities (thin or
        exotic tokens), so a keyword-heavy retry runs once before giving up.
        """
        t_retrieval = time.perf_counter()
        sources = self.retriever.search(
            query=query, limit=limit, alpha=0.5, auto_cut=True
        )
        if not sources:
            logger.info(
                "Retrieval returned 0 sources — retrying with keyword-heavy search"
            )
            sources = self.retriever.search(
                query=query, limit=limit, alpha=0.1, auto_cut=True
            )
        logger.info(
            "[global-search] retrieval_ms=%.0f sources=%d",
            (time.perf_counter() - t_retrieval) * 1000,
            len(sources),
        )
        return sources

    def _generate_answer(
        self, query: str, grounded_sources: list[LectureSearchResultDTO]
    ) -> str:
        """Invoke the answer LLM on the numbered, metadata-tagged context."""
        context = "\n\n".join(
            f"[{i + 1}] [{s.course.name} — {s.lecture.name}, "
            f"{_location_label(s)}]\n{s.snippet}"
            for i, s in enumerate(grounded_sources)
        )
        t_answer = time.perf_counter()
        raw = (self.answer_prompt | self.answer_pipeline).invoke(
            {"context": context, "query": query}
        )
        # raw_len=0 + output_tokens>0 is the fingerprint of a reasoning model
        # exhausting max_tokens on reasoning and returning an empty message
        # (finish_reason=length) — the call returns WITHOUT an exception.
        answer_usage = self.answer_llm.tokens
        logger.info(
            "[global-search] answer_llm_ms=%.0f context_sources=%d "
            "context_chars=%d raw_len=%d input_tokens=%s output_tokens=%s",
            (time.perf_counter() - t_answer) * 1000,
            len(grounded_sources),
            len(context),
            len(raw),
            getattr(answer_usage, "num_input_tokens", None),
            getattr(answer_usage, "num_output_tokens", None),
        )
        return raw

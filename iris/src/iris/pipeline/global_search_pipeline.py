import json
import re
import time

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from weaviate import WeaviateClient

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.config import settings
from iris.domain.search.lecture_search_dto import (
    GlobalSearchResponseDTO,
    LectureSearchResultDTO,
)
from iris.domain.search.search_intent_dto import SearchIntent
from iris.llm import CompletionArguments, LlmRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.llm.llm_configuration import resolve_model
from iris.pipeline.prompts.global_search_prompts import (
    answer_system_prompt,
    hyde_system_prompt,
)
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


class GlobalSearchPipeline(SubPipeline):
    """
    Pipeline that answers a student's question by retrieving relevant course content
    using HyDE (Hypothetical Document Embedding) and then generating a concise answer.

    HyDE improves retrieval precision for Q&A: instead of embedding the question directly,
    it generates a short hypothetical answer first and embeds that. This works because
    answers live closer to answers in the vector space than questions do.
    """

    hyde_llm: IrisLangchainChatModel
    answer_llm: IrisLangchainChatModel
    hyde_pipeline: Runnable
    answer_pipeline: Runnable

    def __init__(self, client: WeaviateClient, local: bool = False):
        super().__init__(implementation_id="global_search_pipeline")
        self.tokens = []
        self.retriever = LectureGlobalSearchRetrieval(client, local=local)

        pipeline_id = "global_search_pipeline"
        hyde_model = resolve_model(pipeline_id, "default", "hyde", local=local)
        answer_model = resolve_model(pipeline_id, "default", "answer", local=local)
        embedding_model = resolve_model(
            pipeline_id, "default", "embedding", local=local
        )
        logger.info(
            "Global search pipeline | mode=%s hyde_llm=%s answer_llm=%s embedding=%s",
            "local" if local else "cloud",
            hyde_model,
            answer_model,
            embedding_model,
        )

        hyde_completion_args = CompletionArguments(max_tokens=150)
        answer_completion_args = CompletionArguments(
            response_format="JSON", max_tokens=600
        )
        self.hyde_llm = IrisLangchainChatModel(
            request_handler=LlmRequestHandler(model_id=hyde_model),
            completion_args=hyde_completion_args,
        )
        self.answer_llm = IrisLangchainChatModel(
            request_handler=LlmRequestHandler(model_id=answer_model),
            completion_args=answer_completion_args,
        )
        self.hyde_pipeline = self.hyde_llm | StrOutputParser()
        self.answer_pipeline = self.answer_llm | StrOutputParser()

        self.hyde_prompt = ChatPromptTemplate.from_messages(
            [("system", hyde_system_prompt), ("user", "{query}")]
        )
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
        Answer a student's question using course content retrieved via HyDE.

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

        # Step 1: Generate a short hypothetical answer to use as the search
        # vector — unless the E4 ablation has HyDE off, in which case the
        # instruct query embedding carries retrieval alone (task I1.9).
        if settings.global_search_hyde_enabled:
            t_hyde = time.perf_counter()
            hypothetical_answer = (self.hyde_prompt | self.hyde_pipeline).invoke(
                {"query": query}
            )
            self._append_tokens(
                self.hyde_llm.tokens, PipelineEnum.IRIS_GLOBAL_SEARCH_PIPELINE
            )
            logger.info(
                "[global-search] hyde_ms=%.0f hyde_output=%r",
                (time.perf_counter() - t_hyde) * 1000,
                hypothetical_answer[:300],
            )
            if not hypothetical_answer.strip():
                logger.warning(
                    "[global-search] hyde_empty_fallback — HyDE returned an "
                    "empty message, retrieving with the instruct query "
                    "embedding only"
                )
        else:
            hypothetical_answer = ""
            logger.info("[global-search] hyde_disabled (ablation)")

        # Step 2: dual-vector candidate retrieval — the instruct query embedding
        # (deterministic baseline) plus, when HyDE produced output, the raw-embedded
        # hypothetical answer. The reranker arbitrates the union, so a drifted or
        # empty HyDE output (reasoning models can exhaust max_tokens and return an
        # empty message without an exception) can never degrade retrieval below the
        # instruct baseline.
        t_retrieval = time.perf_counter()
        sources: list[LectureSearchResultDTO] = self.retriever.search_dual(
            query=query,
            hyde_text=hypothetical_answer,
            alpha=0.5,
            limit=limit,
            auto_cut=True,
        )

        # Fallback: if the HyDE vector produced no hits (e.g. ambiguous query where
        # HyDE generated off-topic content), retry keyword-heavy with the instruct
        # query embedding.
        if not sources:
            logger.info(
                "HyDE retrieval returned 0 sources — retrying with keyword-heavy search"
            )
            sources = self.retriever.search(
                query=query,
                limit=limit,
                alpha=0.1,
                auto_cut=True,
            )
        logger.info(
            "[global-search] retrieval_ms=%.0f sources=%d",
            (time.perf_counter() - t_retrieval) * 1000,
            len(sources),
        )

        if not sources:
            logger.info("[global-search] outcome=no_sources query=%r", query[:120])
            return GlobalSearchResponseDTO(answer=None, sources=[])

        # Step 3: Generate the real answer using numbered context (with metadata so the
        # model knows the course/lecture name and can reference them explicitly)
        grounded_sources = [s for s in sources if s.snippet]
        if not grounded_sources:
            logger.info(
                "[global-search] outcome=no_grounded_sources sources=%d query=%r",
                len(sources),
                query[:120],
            )
            return GlobalSearchResponseDTO(answer=None, sources=[])

        def _location_label(s: LectureSearchResultDTO) -> str:
            page = s.lecture_unit.page_number
            if page == -1:
                meta = s.lecture_unit.display_meta or "video"
                return f"Video @ {meta}"
            return f"Slide {page}"

        context = "\n\n".join(
            f"[{i + 1}] [{s.course.name} — {s.lecture.name}, {_location_label(s)}]\n{s.snippet}"
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

        # Parse structured response — strip markdown code fences if present
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
            used_sources = [
                s for i, s in enumerate(grounded_sources) if i in used_indices
            ]
        else:
            # Plain-text output (the model dropped the JSON envelope). If it ends
            # with a schema-imitating "Used_sources: [..]" line, recover the
            # attribution from it and strip the line; otherwise attach all
            # sources — there is no way to tell which were used.
            match = _TRAILING_USED_SOURCES_RE.search(cleaned)
            if match:
                indices = {
                    int(n) - 1 for n in re.findall(r"\d+", match.group("indices"))
                } - {-1}
                answer = cleaned[: match.start()].rstrip() or None
                used_sources = [
                    s for i, s in enumerate(grounded_sources) if i in indices
                ]
                logger.warning(
                    "[global-search] outcome=parse_salvaged_text used=%d/%d raw=%r",
                    len(used_sources),
                    len(grounded_sources),
                    raw[:300],
                )
            else:
                logger.warning(
                    "[global-search] outcome=parse_failed raw_len=%d raw=%r — "
                    "returning raw text as answer with all sources",
                    len(raw),
                    raw[:300],
                )
                answer = cleaned or None
                used_sources = grounded_sources

        # The model may ALSO write the used_sources line inside a correctly
        # parsed answer string (observed live in the UI). Strip it — it is
        # schema leakage, never content.
        if answer:
            sanitized = _TRAILING_USED_SOURCES_RE.sub("", answer).rstrip()
            if sanitized != answer:
                logger.info(
                    "[global-search] answer_sanitized=trailing_used_sources_line"
                )
                answer = sanitized or None

        # Safety net: if the LLM ignored the null instruction and wrote a short refusal
        # instead of a grounded answer, suppress it so the client never sees a
        # "not covered" message. Only fires on short answers (< 120 chars) to avoid
        # suppressing legitimate answers that mention what the course does not cover.
        if (
            answer
            and len(answer) < 120
            and re.search(
                r"not (covered|mentioned|discussed|found|available|provided|present|included)"
                r"|not (in|part of) the (course|lecture|material|content|slides)"
                r"|no (mention|reference|explanation|definition|description|information)"
                r"|does not (cover|mention|discuss|provide|include|contain|address)"
                r"|cannot (answer|find|provide|address)",
                answer,
                re.IGNORECASE,
            )
        ):
            logger.info(
                "[global-search] outcome=refusal_suppressed suppressed_answer=%r",
                answer,
            )
            answer = None

        # Grounding contract: an answer that cites no sources came from world
        # knowledge, not course content — never show it (observed live: a 4-char
        # "Yes."-style answer with used_sources=[]).
        if answer and not used_sources:
            logger.info(
                "[global-search] outcome=ungrounded_suppressed answer_len=%d "
                "suppressed_answer=%r",
                len(answer),
                answer[:200],
            )
            answer = None

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

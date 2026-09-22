import json
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from weaviate import WeaviateClient

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.domain.search.global_search_dto import (
    AccessContext,
    CourseInfo,
    EntityCandidateDTO,
    EntitySourceDTO,
    GlobalSearchResponseDTO,
    LectureSearchResultDTO,
)
from iris.domain.search.search_intent_dto import SearchIntent
from iris.llm import CompletionArguments, LlmRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.llm.llm_configuration import resolve_model
from iris.pipeline.prompts.global_search_prompts import (
    answer_system_prompt,
    navigate_system_prompt,
)
from iris.pipeline.shared.entity_card_renderer import render_entity_card
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
# The navigate prompt's context labels entities as "[<course> — Course
# information]"; small models occasionally echo the label into prose. The
# suffix is presentation, never content — strip it defensively.
_HEADER_ECHO_RE = re.compile(r"\s*[—-]\s*Course information\b")

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


def _source_label(source: "LectureSearchResultDTO | EntitySourceDTO") -> str:
    """Bracketed context header naming the source's origin and kind."""
    if isinstance(source, EntitySourceDTO):
        if source.course is not None:
            return f"[{source.course.name} — Course information]"
        return "[Course information]"
    return f"[{source.course.name} — {source.lecture.name}, {_location_label(source)}]"


def _today_line(access_context: AccessContext | None) -> str:
    """Semester disambiguation for the grounded prompt's user message.

    Course copies repeat per semester, so an instructor (or a re-enrolled
    student) legitimately retrieves the same exercise or exam with different
    dates. The reranker correctly refuses to prefer a semester; the answer
    model disambiguates instead, because every entity card names its course.
    Measured: without this line both dates are enumerated with labels, with
    it the current semester leads (18/18 correct on the seeded
    semester-conflict suite).
    """
    now = (
        access_context.effective_now_dt()
        if access_context is not None
        else datetime.now(timezone.utc)
    )
    return (
        "\n\nToday is " + now.strftime("%A, %d %B %Y") + ". When sources from "
        "several semesters or course copies conflict, prefer the one most "
        "relevant to today and name which course/semester each date belongs "
        "to."
    )


def _location_label(source: LectureSearchResultDTO) -> str:
    """Human-readable slide/video position tag for the numbered context."""
    page = source.lecture_unit.page_number
    if page == -1:
        meta = source.lecture_unit.display_meta or "video"
        return f"Video @ {meta}"
    return f"Slide {page}"


# The answer prompt (global_search_prompts.py) defines a citation marker as
# appearing DIRECTLY after the claim's punctuation ("worth 10 points.[3]"), with
# a chain of several stacking directly adjacent ("[1][2][3]"). The MATH section
# of that same prompt instructs standalone and inline math alike to be wrapped
# in `$$...$$`, and a claim that IS an equation still gets its marker "directly
# after the claim" per rule 2 — with no sentence punctuation between the
# equation and the marker, e.g. "$$\hat{y}_i = \theta x$$[1]". Matching every
# `[n]` regardless of position corrupts ordinary bracketed content in the
# answer's own prose, e.g. a programming answer's "array[0]" — and, worse,
# silently mis-attributes a source when that bracketed number happens to fall
# in 1..num_sources ("element[1]" read as citing source 1).
#
# The lookbehind therefore anchors on the WHOLE adjacent chain, not each marker
# individually: it requires only the chain's first `[` to sit directly after
# claim punctuation or a closing `$$`, then `(?:\[\d+\])+` greedily consumes any
# further markers stacked with zero characters in between. Anchoring per-marker
# instead (allowing a bare preceding `]` to start a new match on its own) would
# also match plain chained indexing like `matrix[0][1]`: `[0]` is never itself a
# valid start position, but `[1]` immediately follows its closing `]` and would
# wrongly read as a continuation, recording an uncited answer as citing source 1.
#
# Also tolerates exactly one space before the chain. The prompt (rule 2) now says
# explicitly not to write that space, but a live capture still showed the model
# doing it anyway in an otherwise well-formed answer: "...just an association).
# [1][2][3][4][5]" — a genuine claim, correctly grounded, that the strict no-space
# lookbehind matched NOWHERE AT ALL in the whole answer (not just at that one
# marker), which read as "the model wrote no citations whatsoever" and fell back
# to attaching every retrieved source instead of the ones actually cited. A nano
# model's formatting will not be made 100% reliable by a prompt rule alone, so the
# parser has to tolerate the one variation actually observed rather than let a
# single stray space discard every citation in the response.
# Each lookbehind alternative below is individually fixed-width, which Python's
# re module allows even though the alternatives differ in width from each other.
_CITATION_MARKER_RE = re.compile(
    r"(?:(?<=[.!?])|(?<=[.!?] )|(?<=\$\$)|(?<=\$\$ ))(?:\[\d+\])+"
)
_SINGLE_MARKER_RE = re.compile(r"\[(\d+)\]")

# Literal the model outputs INSTEAD of an answer when the sources cannot answer
# the question (plain-text contract; measured 8/8 discipline on nano).
_NO_ANSWER_SENTINEL = "!none!"


def _is_deliberate_refusal(raw: str) -> bool:
    """Whether the raw output IS the explicit !none! sentinel, alone or trailing prose.

    Distinguishes a confident, on-purpose "I choose not to answer" from every other way
    parse_answer_response can end up returning None (a suppressed refusal-in-prose, an
    ungrounded answer, a malformed/flaky JSON null, ...). Only this one is the model
    directly exercising the contract the prompt gives it for declining — the others are
    this pipeline's OWN guards second-guessing an answer the model did not itself refuse.
    """
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
    return cleaned.rstrip(".").strip().casefold().endswith(_NO_ANSWER_SENTINEL)


class _SentinelGateStreamHandler:
    """Buffer streamed deltas until the output can no longer be the !none!
    sentinel, so a no-answer run never flashes text at the student. Same
    pattern as the chat guide's ok-sentinel gate. ``None`` deltas (provider
    retry) reset the stream downstream as well once streaming started."""

    def __init__(self, downstream):
        self._downstream = downstream
        self._buffer = ""
        self._streaming = False

    def __call__(self, delta):
        if delta is None:
            self._buffer = ""
            if self._streaming:
                self._downstream(None)
            return
        if self._streaming:
            self._downstream(delta)
            return
        self._buffer += delta
        stripped = self._buffer.strip()
        if stripped.startswith(_NO_ANSWER_SENTINEL):
            return  # it IS the sentinel — never stream it
        if _NO_ANSWER_SENTINEL.startswith(stripped):
            return  # could still become the sentinel — keep holding
        self._downstream(self._buffer)
        self._buffer = ""
        self._streaming = True


def sanitize_citation_markers(
    answer: str | None, num_sources: int
) -> tuple[str | None, set[int]]:
    """Validate inline citation markers; return (answer, cited 0-based indices).

    The answer LLM appends sentence-level markers like ``[2]`` after the claim
    each source supports. This keeps every in-range marker, DROPS out-of-range
    ones (a hallucinated ``[9]`` over 5 sources must not reach a student), and
    collapses immediately repeated markers (``[1][1]`` -> ``[1]``). Chains of
    DISTINCT adjacent markers (``[1][2][3]``) are the model citing several
    sources for one claim and are preserved; the client groups them visually.

    An answer without markers passes through untouched, which is the
    compatibility path: rendering falls back to the unattributed card.
    """
    if not answer:
        return answer, set()
    cited: set[int] = set()

    def _replace_chain(chain: re.Match) -> str:
        # Everything in one regex match is already one physically-adjacent chain,
        # so "last kept index" only needs to track position within THIS chain —
        # an invalid marker is dropped without breaking that adjacency, so
        # [1][9][1] still collapses to [1] once [9] (out of range) is gone.
        last_kept: int | None = None
        kept: list[int] = []
        for marker in _SINGLE_MARKER_RE.finditer(chain.group(0)):
            index = int(marker.group(1))
            if not 1 <= index <= num_sources:
                continue
            if index == last_kept:
                continue
            kept.append(index)
            last_kept = index
        cited.update(index - 1 for index in kept)
        return "".join(f"[{index}]" for index in kept)

    sanitized = _CITATION_MARKER_RE.sub(_replace_chain, answer)
    return sanitized, cited


def renumber_citation_markers(
    answer: str | None, old_to_new: dict[int, int]
) -> str | None:
    """Rewrite marker numbers after the used-sources filter.

    Markers reference the numbered CONTEXT (1..N over all grounded sources),
    but the response returns only the used sources, so ``[4]`` must become the
    position of that source in the returned list. Unknown numbers are stripped
    defensively; sanitation has already removed them in the normal flow.
    """
    if not answer:
        return answer

    def _replace_chain(chain: re.Match) -> str:
        parts = []
        for marker in _SINGLE_MARKER_RE.finditer(chain.group(0)):
            new = old_to_new.get(int(marker.group(1)))
            if new is not None:
                parts.append(f"[{new}]")
        return "".join(parts)

    return _CITATION_MARKER_RE.sub(_replace_chain, answer)


def _first_appearance_order(answer: str | None, indices: set[int]) -> list[int]:
    """0-based ``indices`` ordered by where their (1-based) marker first appears in
    ``answer``, so renumbering can assign 1, 2, 3... in READING order rather than in
    retrieval-rank order.

    Without this, a source the model happens to cite third in its own ranked context but
    FIRST in the sentences it actually writes gets the higher final number anyway — a reader
    sees "[2]" before "[1]" ever appears, which reads as out of order even though nothing is
    actually wrong. Any index with no marker in the text at all (defensive; should not happen
    once sanitize_citation_markers has already run) is appended at the end, ascending, so
    nothing is silently dropped.
    """
    seen: list[int] = []
    seen_set: set[int] = set()
    if answer:
        # Only markers inside a chain _CITATION_MARKER_RE recognizes as a real citation
        # position (after sentence-ending punctuation or "$$") count as an appearance —
        # scanning _SINGLE_MARKER_RE against the whole answer directly would also match
        # incidental bracket-number text with no citation meaning at all (e.g. "array[2]"
        # in prose about indexing), which can reverse the real citations' order if that
        # index is coincidentally cited for real later on. Same chain-then-marker scoping
        # sanitize_citation_markers and renumber_citation_markers already use above.
        for chain in _CITATION_MARKER_RE.finditer(answer):
            for match in _SINGLE_MARKER_RE.finditer(chain.group(0)):
                old = int(match.group(1)) - 1
                if old in indices and old not in seen_set:
                    seen.append(old)
                    seen_set.add(old)
    remaining = sorted(indices - seen_set)
    return seen + remaining


def parse_answer_response(raw: str, num_sources: int) -> tuple[str | None, set[int]]:
    """Parse the answer LLM's raw output into (answer, used 0-based indices).

    Pure string logic, extracted for unit-testability: structured parsing
    with salvage paths, then the sanitize/suppress guards that decide what a
    student may actually see.
    """
    answer, used_indices = _extract_answer(raw, num_sources)
    if answer:
        answer = _HEADER_ECHO_RE.sub("", answer)
    # Checked on the raw text BEFORE sanitize_citation_markers strips anything: an empty
    # cited_indices is ambiguous on its own between "wrote no markers at all" and "wrote a
    # marker chain that turned out entirely invalid" (e.g. every index out of range) —
    # markers_present resolves that ambiguity by recording whether a chain was attempted
    # at all, regardless of whether any of it survived sanitation.
    markers_present = bool(answer and _CITATION_MARKER_RE.search(answer))
    answer, cited_indices = sanitize_citation_markers(answer, num_sources)
    # cited_indices is the ground truth of what the rendered text actually cites, scanned from
    # its own [n] markers; used_indices is only the model's separate JSON self-report, which can
    # be wrong in both directions. Prefer cited_indices whenever the model wrote any inline
    # markers at all — even where every one of them turned out invalid and cited_indices is
    # therefore empty, since trusting used_indices there would let a JSON self-report re-ground
    # an answer the inline markers themselves failed to support (observed live: an invalid [99]
    # marker stripped to nothing, then silently re-grounded via a non-empty used_sources list).
    # A non-empty cited_indices already covers a source cited inline but left off the JSON list
    # (the prior union's actual intent), while also not attaching every source the JSON
    # over-reports beyond what the text actually references — a union unconditionally did, once
    # observed live attaching 13 sources to an answer that inline-cited only 2 of them. Only
    # when the model wrote no inline markers at all — relying solely on the JSON field for
    # attribution — does used_indices still apply.
    used_indices = cited_indices if markers_present else used_indices
    answer = _sanitize_and_suppress(answer, used_indices)
    return answer, used_indices


def _extract_answer(raw: str, num_sources: int) -> tuple[str | None, set[int]]:
    """Structured parse with salvage paths, in order: markdown fences, JSON
    with LaTeX-backslash repair, embedded-JSON salvage, plain text with a
    trailing "Used_sources: [..]" line (recovering attribution), raw text
    with all sources as the last resort."""
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
    # Plain-text contract: the sentinel is the honest "cannot answer" state. The model is
    # instructed to write it ALONE ("Do NOT write any message explaining why"), but sometimes
    # appends it after an explanation instead of obeying that — observed live as prose ending
    # in " !none!". The trailing sentinel still means the model judged the sources
    # insufficient; treating that explanation as a real, sourced answer would be worse than
    # suppressing it, since nothing here or downstream distinguishes a genuine claim from what
    # the model itself flagged as not actually answerable.
    if _is_deliberate_refusal(raw):
        return None, set()
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
            if isinstance(i, int) and 1 <= i <= num_sources
        }
        return answer, used_indices

    # Plain-text output (the model dropped the JSON envelope). If it ends
    # with a schema-imitating "Used_sources: [..]" line, recover the
    # attribution from it and strip the line.
    match = _TRAILING_USED_SOURCES_RE.search(cleaned)
    if match:
        used_indices = {
            int(n) - 1
            for n in re.findall(r"\d+", match.group("indices"))
            if 1 <= int(n) <= num_sources
        }
        answer = cleaned[: match.start()].rstrip() or None
        logger.warning(
            "[global-search] outcome=parse_salvaged_text used=%d/%d raw=%r",
            len(used_indices),
            num_sources,
            raw[:300],
        )
        return answer, used_indices

    # Plain-text answer with inline markers: the markers ARE the attribution
    # (the caller unions them in); attaching all sources here would overrule
    # them with the whole pool.
    if _CITATION_MARKER_RE.search(cleaned):
        return cleaned or None, set()

    # No inline markers and no other attribution signal at all. Rule 2 requires a marker
    # after every real claim, so plain text that reaches here without a single one is either
    # a genuine answer that dropped the required markers, or — observed live, repeatedly, in
    # several different phrasings — the model explaining a refusal in prose instead of the
    # bare !none! sentinel it was told to use alone. Returning an empty used_indices here,
    # rather than defensively attaching every retrieved source, lets the existing ungrounded
    # guard below (_sanitize_and_suppress) treat this exactly like any other unattributed
    # answer: suppressed, instead of shown to the student dressed up with sources that never
    # actually supported it. This does not try to recognize which specific refusal phrasing
    # the model used — it reacts to the one structural fact any of them share: no markers.
    logger.info(
        "[global-search] outcome=plain_text_no_markers raw_len=%d raw=%r",
        len(raw),
        raw[:400],
    )
    return cleaned or None, set()


_REFUSAL_RE = re.compile(
    r"not (covered|mentioned|discussed|found|available|provided|present|included)"
    r"|not (in|part of) the (course|lecture|material|content|slides)"
    r"|no (mention|reference|explanation|definition|description|information)"
    r"|does not (cover|mention|discuss|provide|include|contain|address)"
    # can(?:not|['’]t): the model sometimes writes the contraction — including with a
    # curly apostrophe (’, U+2019) — instead of "cannot" (observed live: "I can't answer
    # this." slipped past a "cannot"-only pattern and reached the student unsuppressed).
    r"|can(?:not|['’]t) (answer|find|provide|address)",
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


def _distinct_course_names(sources) -> list[str]:
    """Distinct course names across retrieved sources, in first-seen (ranked) order.

    Both LectureSearchResultDTO (always) and EntitySourceDTO (optionally) carry a
    ``course`` field; a source with none (should not happen for a grounded source, but not
    guaranteed by the type checker) is skipped rather than raising.
    """
    seen: dict[str, None] = {}
    for source in sources:
        course = getattr(source, "course", None)
        if course is not None and course.name not in seen:
            seen[course.name] = None
    return list(seen)


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

    def __init__(
        self,
        client: WeaviateClient,
        local: bool = False,
        base_url: str | None = None,
    ):
        super().__init__(implementation_id="global_search_pipeline")
        self.tokens = []
        # base_url scopes retrieval to the Artemis installation that asked; several
        # installations share one Weaviate and their course ids collide.
        self.retriever = LectureGlobalSearchRetrieval(
            client, local=local, base_url=base_url
        )

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

        # Plain-text output (markers carry the attribution, !none! carries the
        # no-answer state) — a JSON envelope would make streamed partials
        # unrenderable fragments.
        answer_completion_args = CompletionArguments(max_tokens=600)
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
                    "you use into the question's language.{today_line}",
                ),
            ]
        )
        # Pointer-only contexts get a NAVIGATION task, not an answer task: the
        # grounded prompt's veto is correct behavior for content QA and wrong
        # for "where is this covered?" (measured: ~80% null on pointer-only
        # contexts vs 8/8 with this prompt).
        self.navigate_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", navigate_system_prompt),
                (
                    "user",
                    "Catalog entries:\n{context}\n\nStudent question: "
                    "{query}\n\nANSWER LANGUAGE = the language of the "
                    "question above. The entries' language is irrelevant — "
                    "write your directions in the question's language.",
                ),
            ]
        )

    @observe(name="Global Search Pipeline")
    def __call__(
        self,
        query: str,
        limit: int = 5,
        intent: SearchIntent | None = None,
        access_context: AccessContext | None = None,
        entity_candidates: list[EntityCandidateDTO] | None = None,
        course_ids: list[int] | None = None,
        exclude_course_ids: list[int] | None = None,
        stream_handler=None,
        stage_handler: Callable[[str, list[str]], None] | None = None,
        **_kwargs,
    ) -> GlobalSearchResponseDTO:
        """
        Answer a student's question from retrieved course content.

        :param query: The student's question or search text.
        :param limit: Maximum number of source segments to retrieve.
        :param intent: Pre-computed intent (SearchIntent). If None,
                       the classifier is called here.
        :param access_context: Optional permissions filter resolved by Artemis, forwarded to every retriever call.
        :param entity_candidates: Pre-fetched, pre-authorized SearchableEntities rows
                                  from Artemis. Rendered as cards, they join the shared
                                  rerank pool so the answer can draw on course
                                  information (dates, points, channels, FAQs) as well
                                  as lecture content.
        :param exclude_course_ids: Courses to hide regardless of course_ids/access
                                   context — only needed for an unrestricted caller
                                   with no course ceiling to narrow locally.
        :param stage_handler: Optional callback fired with a short stage name
                              ("searching", "ranking", "found", "generating") and the
                              distinct course names found so far (empty until "found"
                              fires) as the pipeline crosses into each real phase, so
                              the client can show what is actually happening instead
                              of one static "thinking" message for the whole wait —
                              "ranking" in particular covers the reranker call, which
                              is typically the single slowest part of retrieval, and
                              "found" gives a checkpoint right after it with nothing
                              else to show for that stretch otherwise. Best-effort: a
                              caller that omits it just does not get the intermediate
                              signal, same as before this parameter existed.
        :return: An answer with source references.
        """
        # Guard: skip the full LLM pipeline for navigation queries
        if intent is None:
            intent = classify_intent(query)
        logger.debug("Intent classification | query=%r intent=%s", query[:80], intent)
        if intent == SearchIntent.SKIP_AI:
            sources = self.retriever.search(
                query=query,
                limit=limit,
                course_ids=course_ids,
                exclude_course_ids=exclude_course_ids,
                access_context=access_context,
            )
            return GlobalSearchResponseDTO(answer=None, sources=sources)

        if stage_handler is not None:
            stage_handler("searching", [])
        entity_sources = self._render_entity_sources(entity_candidates)
        sources = self._retrieve_sources(
            query,
            limit,
            access_context,
            entity_sources,
            course_ids,
            exclude_course_ids,
            stage_handler,
        )
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

        if stage_handler is not None:
            # Fires the moment retrieval actually has something to show, rather than leaving
            # "searching" as the only signal for the whole (often the slowest) retrieval +
            # grounding stretch, with generating as the next thing the reader sees.
            stage_handler("found", _distinct_course_names(grounded_sources))

        # Retrieval outcome decides the task: pointer-tier sources were
        # admitted from below the floor because nothing answers the question,
        # so there is nothing to answer FROM, only material to direct the
        # student TO. An above-floor entity card is a real answer source (its
        # details often ARE the answer) and stays with the grounded prompt.
        all_pointers = all(
            isinstance(s, EntitySourceDTO) and s.via_pointer_tier
            for s in grounded_sources
        )
        if stage_handler is not None:
            stage_handler("generating", [])
        raw = self._generate_answer(
            query,
            grounded_sources,
            access_context,
            navigate=all_pointers,
            stream_handler=stream_handler,
        )
        # Snapshot usage right after this call: self.answer_llm.tokens is a fresh
        # TokenUsageDTO instance per invocation, so this reference is independent
        # of whatever the (possible) fallback call below reassigns it to next.
        self._append_tokens(
            self.answer_llm.tokens, PipelineEnum.IRIS_GLOBAL_SEARCH_PIPELINE
        )
        answer, used_indices = parse_answer_response(raw, len(grounded_sources))
        used_sources = [s for i, s in enumerate(grounded_sources) if i in used_indices]

        # Null-to-navigate fallback: the grounded prompt answered null but
        # entity sources exist — retry once as navigation over just those.
        # A genuine negative has no surviving entity sources, so the fallback
        # cannot fire there. Covers where-do-I-find questions and null
        # flakiness of small answer models. Excludes a DELIBERATE !none! specifically: that is
        # the model directly exercising its documented way to decline, not a flaky or
        # over-cautious null this pipeline's own guards produced — retrying it via the
        # navigate prompt, which is deliberately more lenient (rule: "a student prefers a
        # pointer over silence"), relitigates a judgment the model already made on purpose.
        # Observed live: an incomplete question correctly got !none! from the grounded
        # prompt every time, then just as reliably got overridden by the navigate retry
        # pointing at the same course, in the wrong language for the question asked.
        if answer is None and not all_pointers and not _is_deliberate_refusal(raw):
            entity_grounded = [
                s for s in grounded_sources if isinstance(s, EntitySourceDTO)
            ]
            if entity_grounded:
                # The first call may have streamed a plausible-looking draft before
                # this suppression discarded it; the fallback below runs a second,
                # non-streamed LLM call, so without this the client would keep
                # showing that discarded draft — markers and all — for the whole
                # fallback round-trip instead of a thinking state.
                if stream_handler is not None:
                    stream_handler(None)
                raw = self._generate_answer(
                    query, entity_grounded, access_context, navigate=True
                )
                self._append_tokens(
                    self.answer_llm.tokens, PipelineEnum.IRIS_GLOBAL_SEARCH_PIPELINE
                )
                answer, used_indices = parse_answer_response(raw, len(entity_grounded))
                used_sources = [
                    s for i, s in enumerate(entity_grounded) if i in used_indices
                ]
                if answer:
                    logger.info("[global-search] outcome=navigate_fallback")

        # Markers referenced the numbering of whichever context produced the final
        # answer (grounded_sources normally, entity_grounded after the fallback
        # above replaces both answer and used_indices); the response carries only
        # the used sources, so renumber onto that list. Must run AFTER the
        # fallback — renumbering before it left a fallback answer's markers
        # pointing at the wrong (or out-of-range) position in the final list.
        #
        # Citation numbers are assigned in the TRUE order each source is first cited in
        # the text, regardless of type — a reader must never see "[2]" before "[1]" ever
        # appears, whether the two citations are both lecture sources, both entities, or
        # one of each. `sources`/`entitySources` still ship as two separate arrays (the
        # wire format's own split, which the client's marker resolution depends on), so
        # citation_source_types tells the client which of the two arrays marker N
        # resolves into; the two arrays themselves stay internally ordered to match their
        # own subsequence of the reading order below, which is all a client walking
        # citation_source_types with one running counter per type needs to resolve any
        # marker to the right entry — observed live: without this, the client's own
        # fixed "every lecture marker, then every entity marker" resolution rendered an
        # entity cited FIRST in the text as "[5]" while a lecture source cited second
        # rendered as "[1]", even though the server had already numbered them correctly
        # relative to other sources of their OWN type.
        by_old_index = dict(zip(sorted(used_indices), used_sources))
        ordered_used = _first_appearance_order(answer, used_indices)
        indexed_used_sources = [(old, by_old_index[old]) for old in ordered_used]
        old_to_new = {
            old + 1: new + 1 for new, (old, _) in enumerate(indexed_used_sources)
        }
        citation_source_types = [
            "entity" if isinstance(s, EntitySourceDTO) else "lecture"
            for _, s in indexed_used_sources
        ]
        if used_indices:
            logger.info(
                "[global-search] citation_renumbering reading_order=%s "
                "citation_source_types=%s old_to_new=%s",
                ordered_used,
                citation_source_types,
                old_to_new,
            )
        answer = renumber_citation_markers(answer, old_to_new)

        used_lecture = [
            s for _, s in indexed_used_sources if isinstance(s, LectureSearchResultDTO)
        ]
        used_entities = [
            s for _, s in indexed_used_sources if isinstance(s, EntitySourceDTO)
        ]
        if answer:
            logger.info(
                "[global-search] outcome=answered answer_len=%d "
                "used_sources=%d/%d used_entities=%d",
                len(answer),
                len(used_sources),
                len(grounded_sources),
                len(used_entities),
            )
        return GlobalSearchResponseDTO(
            answer=answer,
            sources=used_lecture,
            entity_sources=used_entities,
            citation_source_types=citation_source_types,
        )

    @staticmethod
    def _candidate_reference_date(candidate: EntityCandidateDTO):
        """First parseable calendar anchor of the instance, UTC-normalized."""
        for prop in (
            "start_date",
            "release_date",
            "visible_date",
            "exam_start_date",
            "exam_visible_date",
            "due_date",
            "end_date",
        ):
            value = getattr(candidate, prop, None)
            if not value:
                continue
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        return None

    @staticmethod
    def _render_entity_sources(
        entity_candidates: list[EntityCandidateDTO] | None,
    ) -> list[EntitySourceDTO]:
        """Render Artemis-prefetched candidates into card-carrying sources."""
        sources: list[EntitySourceDTO] = []
        for candidate in entity_candidates or []:
            course = None
            if candidate.course_id is not None and candidate.course_name:
                course = CourseInfo(
                    id=candidate.course_id, name=candidate.course_name.strip()
                )
            sources.append(
                EntitySourceDTO(
                    entity_type=candidate.entity_type,
                    entity_id=candidate.entity_id,
                    course=course,
                    title=(candidate.title or "").strip(),
                    snippet=render_entity_card(candidate),
                    link=candidate.link,
                    exercise_type=candidate.exercise_type,
                    reference_date=GlobalSearchPipeline._candidate_reference_date(
                        candidate
                    ),
                )
            )
        return sources

    def _retrieve_sources(
        self,
        query: str,
        limit: int,
        access_context: AccessContext | None = None,
        entity_sources: list[EntitySourceDTO] | None = None,
        course_ids: list[int] | None = None,
        exclude_course_ids: list[int] | None = None,
        stage_handler: Callable[[str, list[str]], None] | None = None,
    ) -> list["LectureSearchResultDTO | EntitySourceDTO"]:
        """Candidate retrieval with the instruct query embedding.

        The reranker orders the pool on one calibrated scale and the
        threshold gates it — an all-below-threshold pool is the honest
        "no content exists" state and skips the answer LLM entirely. An empty
        pool can also mean the semantic lane missed named entities (thin or
        exotic tokens), so a keyword-heavy retry runs once before giving up.
        """
        # The retriever's own "ranking" phase carries no course names of its own (that is
        # what the "found" stage right after this method returns is for) — it exists purely
        # to keep the reader from staring at "Searching course material…" through the
        # slowest part of retrieval with nothing else to show for it.
        on_phase = (
            (lambda phase: stage_handler(phase, []))
            if stage_handler is not None
            else None
        )
        t_retrieval = time.perf_counter()
        sources = self.retriever.search(
            query=query,
            limit=limit,
            alpha=0.5,
            course_ids=course_ids,
            exclude_course_ids=exclude_course_ids,
            auto_cut=True,
            access_context=access_context,
            entity_sources=entity_sources,
            on_phase=on_phase,
        )
        if not sources:
            logger.info(
                "Retrieval returned 0 sources — retrying with keyword-heavy search"
            )
            sources = self.retriever.search(
                query=query,
                limit=limit,
                alpha=0.1,
                course_ids=course_ids,
                exclude_course_ids=exclude_course_ids,
                auto_cut=True,
                access_context=access_context,
                entity_sources=entity_sources,
                on_phase=on_phase,
            )
        logger.info(
            "[global-search] retrieval_ms=%.0f sources=%d",
            (time.perf_counter() - t_retrieval) * 1000,
            len(sources),
        )
        return sources

    def _generate_answer(
        self,
        query: str,
        grounded_sources: list["LectureSearchResultDTO | EntitySourceDTO"],
        access_context: AccessContext | None = None,
        navigate: bool = False,
        stream_handler=None,
    ) -> str:
        """Invoke the answer LLM on the numbered, metadata-tagged context.

        With a ``stream_handler``, deltas stream through the sentinel gate so
        partial answers reach the client while the model generates; markers in
        partials stream raw and the client renders them progressively. The
        terminal update still carries the sanitized, renumbered answer.
        """
        context = "\n\n".join(
            f"[{i + 1}] {_source_label(s)}\n{s.snippet}"
            for i, s in enumerate(grounded_sources)
        )
        t_answer = time.perf_counter()
        prompt = self.navigate_prompt if navigate else self.answer_prompt
        variables: dict[str, str] = {"context": context, "query": query}
        if not navigate:
            variables["today_line"] = _today_line(access_context)
        if stream_handler is not None:
            self.answer_llm.completion_args.stream_handler = _SentinelGateStreamHandler(
                stream_handler
            )
        try:
            raw = (prompt | self.answer_pipeline).invoke(variables)
        finally:
            self.answer_llm.completion_args.stream_handler = None
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

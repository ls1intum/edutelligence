"""Inline citations: short handles the answer model writes while it streams.

Citations used to be attached after the answer was generated: a second LLM call
re-wrote the whole answer to insert source ids, followed by keyword/summary calls
per cited source. Both sat on the critical path, and because the raw agent output
is streamed *before* the post-processing runs, the streamed draft never contained
any citations at all.

Instead, the answer model now writes a short handle -- ``[cite:3]`` -- inline while
it generates. It only has to copy one or two digits, so the extra output is
negligible and there is little to garble. This module owns both sides of that
handle:

- :class:`CitationRegistry` hands out the handles when content is retrieved and
  expands them back into the wire format the client parses,
  ``[cite:<type>:<entity_id>:<page>:<start>:<end>:<keyword>:<summary>]``.
- :class:`CitationEnricher` produces the keyword and summary fields.

The enrichment for a handle starts as soon as the handle is *seen in the stream*,
so it runs while the model is still writing the rest of the answer. By the time
the answer is complete the results are normally ready, which leaves no LLM call
on the critical path.
"""

import os
import re
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.common.token_usage_dto import TokenUsageDTO
from iris.llm import CompletionArguments, LlmRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.llm.llm_configuration import resolve_model
from iris.tracing import TracedThreadPoolExecutor

logger = get_logger(__name__)

# The handle the answer model writes inline, e.g. ``[cite:3]``.
CITATION_HANDLE_PATTERN = re.compile(r"\[cite:(\d+)\]")

# A handle the model is halfway through typing at the very end of a partial
# ("... siehe [cit"). Such a fragment must never reach the client, or the draft
# briefly shows a broken marker. Matching only prefixes of "[cite:<digits>"
# keeps unrelated text -- including a markdown link being typed -- untouched
# beyond the opening bracket, which reappears on the next tick anyway.
TRAILING_HANDLE_FRAGMENT_PATTERN = re.compile(r"\[(?:c(?:i(?:t(?:e(?::\d*)?)?)?)?)?$")

# How long assembling the final answer may wait for enrichment that is still
# running. Exceeding it degrades to empty keyword/summary fields rather than
# holding the answer back -- the same trade-off the post-hoc pipeline made when
# enrichment failed.
FINAL_ENRICHMENT_TIMEOUT_SECONDS = 2.0

# Summaries are independent of each other and run in parallel. Keywords must be
# generated one at a time: each call is told which keywords are already taken so
# the bubbles stay distinguishable, which only works if they run in order.
_SUMMARY_WORKERS = 4
_KEYWORD_WORKERS = 1

CITE_TYPE_LECTURE = "L"
CITE_TYPE_FAQ = "F"

_PIPELINE_ID = "citation_pipeline"


def _format_part(value) -> str:
    return "" if value is None else str(value)


@dataclass
class _Source:
    """A citable piece of retrieved content and its coordinates in Artemis."""

    cite_type: str
    entity_id: str
    page: str
    start: str
    end: str
    content: str


class CitationEnricher:
    """Generates the keyword and summary fields of a citation marker.

    Uses a small, cheap model (the ``keyword_summary`` role). Instances are
    shared across requests and called from worker threads, so every call builds
    its own chat model over the shared request handler.
    """

    def __init__(self, local: bool = False):
        keyword_model = resolve_model(
            _PIPELINE_ID, "default", "keyword_summary", local=local
        )
        self._request_handler = LlmRequestHandler(model_id=keyword_model)
        self._completion_args = CompletionArguments(temperature=0)
        self._keyword_prompt_str = _read_prompt("citation_keyword_prompt.txt")
        self._summary_prompt_str = _read_prompt("citation_summary_prompt.txt")

    def generate_keyword(
        self, content: str, language_instruction: str, used_keywords: list[str]
    ) -> tuple[str, list[TokenUsageDTO]]:
        prompt = PromptTemplate(
            template=language_instruction + self._keyword_prompt_str,
            input_variables=["Paragraph", "UsedKeywords"],
        )
        return self._invoke(
            prompt,
            {"Paragraph": content, "UsedKeywords": ", ".join(sorted(used_keywords))},
        )

    def generate_summary(
        self, content: str, language_instruction: str
    ) -> tuple[str, list[TokenUsageDTO]]:
        prompt = PromptTemplate(
            template=language_instruction + self._summary_prompt_str,
            input_variables=["Paragraph"],
        )
        return self._invoke(prompt, {"Paragraph": content})

    def _invoke(self, prompt, variables) -> tuple[str, list[TokenUsageDTO]]:
        # Thread-local model instance: IrisLangchainChatModel accumulates token
        # usage on itself, so sharing one across workers would race.
        llm = IrisLangchainChatModel(
            request_handler=self._request_handler,
            completion_args=self._completion_args,
        )
        raw = str((prompt | llm | StrOutputParser()).invoke(variables)).strip()
        tokens = []
        for token in llm.tokens:
            token.pipeline = PipelineEnum.IRIS_CITATION_PIPELINE
            tokens.append(token)
        return _sanitize_field(raw), tokens


def _read_prompt(filename: str) -> str:
    path = os.path.join(os.path.dirname(__file__), "..", "prompts", filename)
    with open(path, "r", encoding="utf-8") as file:
        return file.read()


def _sanitize_field(value: str) -> str:
    """Strip characters that would break out of the citation marker syntax."""
    if not value:
        return ""
    cleaned = value.replace(":", " -").replace("]", ")").replace("[", "(")
    return " ".join(cleaned.split())


class CitationRegistry:
    """Per-request map from inline citation handles to source metadata.

    Retrieval registers content and gets back a handle to show the answer model;
    :meth:`render` turns the handles the model wrote back into full markers. The
    same ``render`` runs on every streamed partial and once on the final answer,
    so it is called from the partial-sender thread and the pipeline thread alike
    and guards its state with a lock.
    """

    def __init__(
        self,
        enricher: Optional[CitationEnricher] = None,
        user_language: str = "en",
    ):
        # Without an enricher nothing can be registered meaningfully, but
        # rendering still works and drops every handle -- that is the state a
        # pipeline which does not cite runs in.
        self._enricher = enricher
        self._language_instruction = (
            "Format all citations and references in German.\n\n"
            if user_language == "de"
            else "Format all citations and references in English.\n\n"
        )
        self._lock = threading.RLock()
        self._sources: dict[int, _Source] = {}
        self._handles_by_key: dict[str, int] = {}
        self._next_number = 0
        self._keyword_futures: dict[int, Future] = {}
        self._summary_futures: dict[int, Future] = {}
        self._used_keywords: set[str] = set()
        self._keyword_pool: Optional[TracedThreadPoolExecutor] = None
        self._summary_pool: Optional[TracedThreadPoolExecutor] = None
        self._closed = False
        self.tokens: list[TokenUsageDTO] = []

    # -- registration ----------------------------------------------------

    def register(
        self,
        cite_type: str,
        entity_id,
        content: str,
        *,
        page=None,
        start=None,
        end=None,
        dedup_key: Optional[str] = None,
    ) -> str:
        """Register citable content and return the handle to show the model.

        ``dedup_key`` (the chunk's uuid) makes the same chunk reachable under a
        single handle even when it arrives twice -- e.g. the slide the student is
        currently viewing is injected into the system prompt *and* comes back
        from the retrieval tool.
        """
        key = (
            dedup_key
            or f"{cite_type}:{_format_part(entity_id)}:{_format_part(page)}"
            f":{_format_part(start)}:{_format_part(end)}"
        )
        with self._lock:
            existing = self._handles_by_key.get(key)
            if existing is not None:
                return f"[cite:{existing}]"
            self._next_number += 1
            number = self._next_number
            self._handles_by_key[key] = number
            self._sources[number] = _Source(
                cite_type=cite_type,
                entity_id=_format_part(entity_id),
                page=_format_part(page),
                start=_format_part(start),
                end=_format_part(end),
                content=content or "",
            )
        return f"[cite:{number}]"

    def has_sources(self) -> bool:
        with self._lock:
            return bool(self._sources)

    # -- rendering -------------------------------------------------------

    def render(self, text: str, *, final: bool = False) -> str:
        """Expand the handles in ``text`` into full citation markers.

        Kicks off enrichment for handles seen for the first time, which is what
        keeps the LLM calls off the critical path. A handle whose enrichment is
        still running is omitted from a partial and pops in on a later tick; in
        the final answer it is waited for, bounded by
        ``FINAL_ENRICHMENT_TIMEOUT_SECONDS``.
        """
        if not text:
            return text

        self._start_enrichment(text)
        deadline = (
            time.monotonic() + FINAL_ENRICHMENT_TIMEOUT_SECONDS if final else None
        )
        rendered = CITATION_HANDLE_PATTERN.sub(
            lambda match: self._render_handle(match, deadline), text
        )
        if not final:
            rendered = TRAILING_HANDLE_FRAGMENT_PATTERN.sub("", rendered)
        return rendered

    def _render_handle(self, match: re.Match, deadline: Optional[float]) -> str:
        number = int(match.group(1))
        with self._lock:
            source = self._sources.get(number)
        if source is None:
            # A handle the model invented. Dropping it is the only safe option:
            # there is no source behind it, so it can never become a bubble.
            return ""

        if source.content.strip():
            enrichment = self._enrichment_result(number, deadline)
            if enrichment is None:
                # Still running and this is a partial -- hide the marker for now.
                return ""
            keyword, summary = enrichment
        else:
            # Nothing to summarise; the marker still carries the source
            # coordinates, so the client can link to it.
            keyword, summary = "", ""
        return (
            f"[cite:{source.cite_type}:{source.entity_id}:{source.page}"
            f":{source.start}:{source.end}:{keyword}:{summary}]"
        )

    def _enrichment_result(
        self, number: int, deadline: Optional[float]
    ) -> Optional[tuple[str, str]]:
        with self._lock:
            keyword_future = self._keyword_futures.get(number)
            summary_future = self._summary_futures.get(number)

        if keyword_future is None or summary_future is None:
            # Not submitted yet, or the registry was closed before it ran.
            return ("", "") if deadline is not None else None

        if deadline is None:
            if not (keyword_future.done() and summary_future.done()):
                return None
            return (_future_value(keyword_future), _future_value(summary_future))

        keyword = _future_value(keyword_future, _remaining(deadline))
        summary = _future_value(summary_future, _remaining(deadline))
        return keyword, summary

    # -- enrichment ------------------------------------------------------

    def _start_enrichment(self, text: str) -> None:
        for match in CITATION_HANDLE_PATTERN.finditer(text):
            number = int(match.group(1))
            with self._lock:
                if self._closed or self._enricher is None:
                    continue
                if number in self._keyword_futures:
                    continue
                source = self._sources.get(number)
                if source is None or not source.content.strip():
                    continue
                self._keyword_futures[number] = self._get_keyword_pool().submit(
                    self._run_keyword, source.content
                )
                self._summary_futures[number] = self._get_summary_pool().submit(
                    self._run_summary, source.content
                )

    def _run_keyword(self, content: str) -> str:
        # Runs on the single keyword worker, so reading the taken keywords here
        # (rather than at submit time) is what makes them unique across bubbles.
        with self._lock:
            used = sorted(self._used_keywords)
        keyword, tokens = self._enricher.generate_keyword(
            content, self._language_instruction, used
        )
        with self._lock:
            self.tokens.extend(tokens)
            if keyword:
                self._used_keywords.add(keyword)
        return keyword

    def _run_summary(self, content: str) -> str:
        summary, tokens = self._enricher.generate_summary(
            content, self._language_instruction
        )
        with self._lock:
            self.tokens.extend(tokens)
        return summary

    def _get_keyword_pool(self) -> TracedThreadPoolExecutor:
        if self._keyword_pool is None:
            self._keyword_pool = TracedThreadPoolExecutor(
                max_workers=_KEYWORD_WORKERS, thread_name_prefix="citation-keyword"
            )
        return self._keyword_pool

    def _get_summary_pool(self) -> TracedThreadPoolExecutor:
        if self._summary_pool is None:
            self._summary_pool = TracedThreadPoolExecutor(
                max_workers=_SUMMARY_WORKERS, thread_name_prefix="citation-summary"
            )
        return self._summary_pool

    def close(self) -> None:
        """Release the worker pools. Idempotent; safe to call without any run."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            pools = (self._keyword_pool, self._summary_pool)
            self._keyword_pool = None
            self._summary_pool = None
        for pool in pools:
            if pool is not None:
                pool.shutdown(wait=False)


def _remaining(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


def _future_value(future: Future, timeout: Optional[float] = None) -> str:
    try:
        return future.result(timeout=timeout) or ""
    except Exception as error:
        logger.warning("Citation enrichment unavailable, using empty field: %s", error)
        return ""

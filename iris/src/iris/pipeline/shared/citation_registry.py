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

import contextvars
import os
import re
import threading
from concurrent.futures import Future, wait
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

logger = get_logger(__name__)

# The handle the answer model writes inline, e.g. ``[cite:3]``.
CITATION_HANDLE_PATTERN = re.compile(r"\[cite:(\d+)\]")

# A handle the model is halfway through typing at the very end of a partial
# ("... siehe [cit"). Such a fragment must never reach the client, or the draft
# briefly shows a broken marker. Matching only prefixes of "[cite:<digits>"
# keeps unrelated text -- including a markdown link being typed -- untouched
# beyond the opening bracket, which reappears on the next tick anyway.
TRAILING_HANDLE_FRAGMENT_PATTERN = re.compile(r"\[(?:c(?:i(?:t(?:e(?::\d*)?)?)?)?)?$")

CITE_TYPE_LECTURE = "L"
CITE_TYPE_FAQ = "F"

_PIPELINE_ID = "citation_enricher"


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
        # Thread-local model instance: IrisLangchainChatModel records the usage
        # of its last call on itself, so sharing one across workers would race.
        llm = IrisLangchainChatModel(
            request_handler=self._request_handler,
            completion_args=self._completion_args,
        )
        raw = str((prompt | llm | StrOutputParser()).invoke(variables)).strip()
        # ``tokens`` is a single TokenUsageDTO, not a list, and stays None if the
        # model reported no usage.
        tokens: list[TokenUsageDTO] = []
        if llm.tokens is not None:
            llm.tokens.pipeline = PipelineEnum.IRIS_CITATION_PIPELINE
            tokens.append(llm.tokens)
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
        self._enrichment_futures: dict[int, Future] = {}
        self._closed = False
        self.tokens: list[TokenUsageDTO] = []

    @property
    def has_sources(self) -> bool:
        with self._lock:
            return bool(self._sources)

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
            source = _Source(
                cite_type=cite_type,
                entity_id=_format_part(entity_id),
                page=_format_part(page),
                start=_format_part(start),
                end=_format_part(end),
                content=content or "",
            )
            self._handles_by_key[key] = number
            self._sources[number] = source
        return f"[cite:{number}]"

    # -- rendering -------------------------------------------------------

    def render(self, text: str, *, final: bool = False) -> str:
        """Expand the handles in ``text`` into full citation markers."""
        if not text:
            return text

        self._start_enrichment(text)
        if final:
            self._await_enrichment(text)
        rendered = CITATION_HANDLE_PATTERN.sub(
            lambda match: self._render_handle(int(match.group(1)), final), text
        )
        if not final:
            rendered = TRAILING_HANDLE_FRAGMENT_PATTERN.sub("", rendered)
        return rendered

    def _await_enrichment(self, text: str) -> None:
        pending = []
        with self._lock:
            seen: set[int] = set()
            for match in CITATION_HANDLE_PATTERN.finditer(text):
                number = int(match.group(1))
                if number in seen:
                    continue
                seen.add(number)
                future = self._enrichment_futures.get(number)
                if future is not None and not future.done():
                    pending.append(future)
        if not pending:
            return
        wait(pending)

    def _render_handle(self, number: int, final: bool) -> str:
        with self._lock:
            source = self._sources.get(number)
            future = self._enrichment_futures.get(number)
        if source is None:
            return ""

        if source.content.strip():
            if future is None:
                if not final:
                    return ""
                keyword, summary = "", ""
            elif not future.done():
                if not final:
                    return ""
                keyword, summary = _future_value(future)
            else:
                keyword, summary = _future_value(future)
        else:
            keyword, summary = "", ""
        return (
            f"[cite:{source.cite_type}:{source.entity_id}:{source.page}"
            f":{source.start}:{source.end}:{keyword}:{summary}]"
        )

    def _start_enrichment(self, text: str) -> None:
        for match in CITATION_HANDLE_PATTERN.finditer(text):
            number = int(match.group(1))
            with self._lock:
                source = self._sources.get(number)
                if source is None:
                    continue
                self._start_enrichment_for_number(number, source)

    def _start_enrichment_for_number(self, number: int, source: _Source) -> None:
        if self._closed or self._enricher is None:
            return
        if number in self._enrichment_futures:
            return
        if not source.content.strip():
            return
        self._enrichment_futures[number] = _run_in_thread(
            self._run_enrichment, source.content
        )

    def _run_enrichment(self, content: str) -> tuple[str, str]:
        with self._lock:
            if self._closed:
                return "", ""
        keyword, keyword_tokens = self._enricher.generate_keyword(
            content, self._language_instruction, []
        )
        summary, tokens = self._enricher.generate_summary(
            content, self._language_instruction
        )
        with self._lock:
            self.tokens.extend(keyword_tokens)
            self.tokens.extend(tokens)
        return keyword, summary

    def close(self) -> None:
        """Stop enrichment for this run. Idempotent."""
        with self._lock:
            self._closed = True


def _run_in_thread(fn, *args) -> Future:
    """Start ``fn`` right away on its own daemon thread."""
    future: Future = Future()
    context = contextvars.copy_context()

    def run() -> None:
        if not future.set_running_or_notify_cancel():
            return
        try:
            future.set_result(context.run(fn, *args))
        except BaseException as error:  # pylint: disable=broad-except
            future.set_exception(error)

    threading.Thread(target=run, daemon=True, name="citation-enrichment").start()
    return future


def _future_value(future: Future) -> tuple[str, str]:
    """Read a finished enrichment; anything else degrades to empty fields."""
    if not future.done():
        return "", ""
    try:
        result = future.result()
        if not result:
            return "", ""
        return result
    except Exception as error:
        logger.warning("Citation enrichment failed, using empty fields: %s", error)
        return "", ""

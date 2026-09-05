"""Inline citation handles and their enrichment."""

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

# Hide a trailing partial handle like ``[cit`` in streamed drafts.
TRAILING_HANDLE_FRAGMENT_PATTERN = re.compile(r"\[(?:c(?:i(?:t(?:e(?::\d*)?)?)?)?)?$")

CITE_TYPE_LECTURE = "L"
CITE_TYPE_FAQ = "F"

# Config key under ``llm_configuration``; renaming it breaks deployed setups.
_PIPELINE_ID = "citation_pipeline"

# How long ``close()`` waits for workers whose model call is already in flight.
# Bounded so a hanging completion cannot pin the request thread.
_SHUTDOWN_TIMEOUT_SECONDS = 5.0


def _format_part(value) -> str:
    return "" if value is None else str(value)


def _handle_numbers(text: str) -> list[int]:
    """The handle numbers in ``text``, de-duplicated, in order of first use."""
    return list(
        dict.fromkeys(
            int(match.group(1)) for match in CITATION_HANDLE_PATTERN.finditer(text)
        )
    )


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
    """Generates citation keyword and summary fields."""

    def __init__(self, local: bool = False):
        keyword_model = resolve_model(
            _PIPELINE_ID, "default", "keyword_summary", local=local
        )
        self._request_handler = LlmRequestHandler(model_id=keyword_model)
        self._completion_args = CompletionArguments(temperature=0)
        self._keyword_prompt_str = _read_prompt("citation_keyword_prompt.txt")
        self._summary_prompt_str = _read_prompt("citation_summary_prompt.txt")

    def generate_keyword(
        self, content: str, language_instruction: str
    ) -> tuple[str, list[TokenUsageDTO]]:
        prompt = PromptTemplate(
            template=language_instruction + self._keyword_prompt_str,
            input_variables=["Paragraph"],
        )
        return self._invoke(prompt, {"Paragraph": content})

    def generate_summary(
        self, content: str, language_instruction: str
    ) -> tuple[str, list[TokenUsageDTO]]:
        prompt = PromptTemplate(
            template=language_instruction + self._summary_prompt_str,
            input_variables=["Paragraph"],
        )
        return self._invoke(prompt, {"Paragraph": content})

    def _invoke(self, prompt, variables) -> tuple[str, list[TokenUsageDTO]]:
        # ``IrisLangchainChatModel`` stores token usage on the instance.
        llm = IrisLangchainChatModel(
            request_handler=self._request_handler,
            completion_args=self._completion_args,
        )
        raw = str((prompt | llm | StrOutputParser()).invoke(variables)).strip()
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
    """Per-request map from citation handles to source metadata."""

    def __init__(
        self,
        enricher: Optional[CitationEnricher] = None,
        user_language: str = "en",
    ):
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
        """Register citable content and return its handle."""
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
        with self._lock:
            pending = [
                self._enrichment_futures[number]
                for number in _handle_numbers(text)
                if number in self._enrichment_futures
            ]
        if pending:
            wait(pending)

    def _render_handle(self, number: int, final: bool) -> str:
        with self._lock:
            source = self._sources.get(number)
            future = self._enrichment_futures.get(number)
        if source is None:
            return ""

        if not source.content.strip():
            keyword, summary = "", ""
        elif not final and (future is None or not future.done()):
            # Enrichment is still running; hide the marker until the final render.
            return ""
        else:
            keyword, summary = _future_value(future) if future is not None else ("", "")
        return (
            f"[cite:{source.cite_type}:{source.entity_id}:{source.page}"
            f":{source.start}:{source.end}:{keyword}:{summary}]"
        )

    def _start_enrichment(self, text: str) -> None:
        if self._enricher is None:
            return
        for number in _handle_numbers(text):
            with self._lock:
                if self._closed or number in self._enrichment_futures:
                    continue
                source = self._sources.get(number)
                if source is None or not source.content.strip():
                    continue
                self._enrichment_futures[number] = _run_in_thread(
                    self._run_enrichment, source.content
                )

    def _run_enrichment(self, content: str) -> tuple[str, str]:
        if self._is_closed():
            return "", ""
        keyword, keyword_tokens = self._enricher.generate_keyword(
            content, self._language_instruction
        )
        self._record_tokens(keyword_tokens)
        # ``close()`` can land while the call above is in flight. Bail out here
        # instead of spending a second completion whose result is discarded —
        # this also halves how long ``close()`` has to wait for us.
        if self._is_closed():
            return "", ""
        summary, summary_tokens = self._enricher.generate_summary(
            content, self._language_instruction
        )
        self._record_tokens(summary_tokens)
        return keyword, summary

    def _is_closed(self) -> bool:
        with self._lock:
            return self._closed

    def _record_tokens(self, tokens: list[TokenUsageDTO]) -> None:
        with self._lock:
            self.tokens.extend(tokens)

    def close(self) -> None:
        """Stop enrichment for this run and wait for in-flight workers.

        Setting the flag alone only stops workers that have not reached their
        first model call yet. A running completion cannot be cancelled --
        ``Future.cancel()`` is useless once the worker started -- so we also
        wait for the ones already past that check, otherwise they would keep
        calling the model after the pipeline is done with them. The wait is
        bounded: a hanging completion must not pin the request thread.
        Idempotent.
        """
        with self._lock:
            self._closed = True
            pending = [
                future
                for future in self._enrichment_futures.values()
                if not future.done()
            ]
        if not pending:
            return
        _, still_running = wait(pending, timeout=_SHUTDOWN_TIMEOUT_SECONDS)
        if still_running:
            logger.warning(
                "Citation enrichment still running %ss after close (%d worker(s))",
                _SHUTDOWN_TIMEOUT_SECONDS,
                len(still_running),
            )


def _run_in_thread(fn, *args) -> Future:
    """Start ``fn`` on a daemon thread."""
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
    """Read a finished enrichment, else fall back to empty fields."""
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

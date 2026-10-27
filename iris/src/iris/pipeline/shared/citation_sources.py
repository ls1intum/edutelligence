"""Source markers written by the chat agent and the cite blocks they become.

Retrieval tools print a ``Source id: [src:N]`` line next to every citable piece of content.
The agent puts ``[src:N]`` after each sentence that uses that content. Only Pyris turns the
markers into the cite blocks Artemis renders,
``[cite:<L|F>:<entity id>:<page>:<start>:<end>:<keyword>:<summary>]``, so a cite block in a
message always comes from content a tool really returned in this run.
"""

import re
from dataclasses import dataclass
from threading import Lock
from typing import Callable, Iterable, Optional

from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureTranscriptionRetrievalDTO,
    LectureUnitPageChunkRetrievalDTO,
)
from iris.retrieval.faq_retrieval_utils import format_faqs
from iris.vector_database.faq_schema import FaqSchema

# A well-formed marker, e.g. ``[src:7]``.
SOURCE_MARKER_RE = re.compile(r"\[src:(\d+)\]")
# The line a tool prints above citable content (see ``source_id_line``).
_SOURCE_ID_LINE_RE = re.compile(r"Source id: \[src:(\d+)\]\n")
# The frame around slide and transcript text after its id line, in the lecture tool and in
# the current view alike. One shared frame keeps a cut result from passing for another one.
CONTENT_OPEN = "Content:\n---"
CONTENT_CLOSE = "---"
# Anything that starts like a marker but is not a well-formed one: ``[src:12`` cut off at the end,
# ``[src:x]``, ``[src: 3]``. Matched after the well-formed markers are handled.
_BROKEN_SOURCE_MARKER_RE = re.compile(r"[ \t]*\[src:[^\]\n]{0,20}\]?")
# A cite block. The agent must never write one itself: Artemis resolves every cite block it finds.
CITE_BLOCK_RE = re.compile(r"[ \t]*\[cite:[^\]]*\]?")
# One or more markers that follow each other, with only horizontal space in between.
_MARKER_CHAIN_RE = re.compile(r"[ \t]*\[src:\d+\](?:[ \t]*\[src:\d+\])*")
# Fenced code (an unclosed fence runs to the end of the text) and inline code.
_CODE_RE = re.compile(r"```.*?(?:```|\Z)|`[^`\n]+`", re.DOTALL)
# The end of a draft that may still grow into a marker or a cite block.
_PENDING_MARKER_RE = re.compile(
    r"\[(?:s(?:r(?:c(?::\d*)?)?)?)?\Z|\[c(?:i(?:t(?:e(?::[^\]\n]*)?)?)?)?\Z"
)


@dataclass(frozen=True)
class CitationSource:
    """One citable piece of content and the fields of its cite block."""

    source_id: int
    cite_type: str  # "L" (lecture) or "F" (FAQ)
    entity_id: str  # lecture unit id or FAQ id
    page: str  # slide index in the deck, only for slides
    start: str  # transcription start in seconds
    end: str  # transcription end in seconds
    content: str
    # The complete text a tool prints for the source right after its id line (see
    # CitationSourceRegistry.mark_delivered).
    delivery_text: str = ""

    def cite_block(self, keyword: str = "", summary: str = "") -> str:
        return (
            f"[cite:{self.cite_type}:{self.entity_id}:{self.page}:{self.start}:"
            f"{self.end}:{keyword}:{summary}]"
        )


def _part(value) -> str:
    return "" if value is None else str(value)


class CitationSourceRegistry:
    """Hands out the source ids of one chat run.

    The same piece of content always gets the same id, also when the current view and a
    retrieval both return it. Ids are never reused.

    With ``require_delivery`` a source becomes citable only once its id line and its complete
    content reached the model (``mark_delivered``). A source is registered when a tool formats
    it, which is before an output limit may cut the result, and the current view registers its
    material before the tool that reads it out has run. Without delivery tracking every
    registered source is citable for the whole run.
    """

    def __init__(self, require_delivery: bool = False) -> None:
        self._lock = Lock()
        self._ids_by_key: dict[tuple[str, str], int] = {}
        self._sources: dict[int, CitationSource] = {}
        self._require_delivery = require_delivery
        self._delivered: set[int] = set()

    def _register(
        self, key: tuple[str, str], build: Callable[[int], CitationSource]
    ) -> int:
        with self._lock:
            source_id = self._ids_by_key.get(key)
            if source_id is None:
                source_id = len(self._sources) + 1
                self._ids_by_key[key] = source_id
                self._sources[source_id] = build(source_id)
            return source_id

    def register_page_chunk(
        self, chunk: LectureUnitPageChunkRetrievalDTO
    ) -> Optional[int]:
        if not chunk.page_text_content:
            return None
        return self._register(
            ("page_chunk", chunk.uuid),
            lambda source_id: CitationSource(
                source_id=source_id,
                cite_type="L",
                entity_id=_part(chunk.lecture_unit_id),
                page=_part(chunk.page_number),
                start="",
                end="",
                content=chunk.page_text_content,
                delivery_text=framed_content(chunk.page_text_content),
            ),
        )

    def register_transcription(
        self, segment: LectureTranscriptionRetrievalDTO
    ) -> Optional[int]:
        if not segment.segment_text:
            return None
        start = (
            int(segment.segment_start_time)
            if segment.segment_start_time is not None
            else None
        )
        end = (
            int(segment.segment_end_time)
            if segment.segment_end_time is not None
            else None
        )
        return self._register(
            ("transcription", segment.uuid),
            lambda source_id: CitationSource(
                source_id=source_id,
                cite_type="L",
                entity_id=_part(segment.lecture_unit_id),
                page="",
                start=_part(start),
                end=_part(end),
                content=segment.segment_text,
                delivery_text=framed_content(segment.segment_text),
            ),
        )

    def register_faq(self, faq: dict) -> Optional[int]:
        faq_id = faq.get(FaqSchema.FAQ_ID.value)
        question = faq.get(FaqSchema.QUESTION_TITLE.value) or ""
        answer = faq.get(FaqSchema.QUESTION_ANSWER.value) or ""
        content = f"{question} {answer}".strip()
        if faq_id is None or not content:
            return None
        return self._register(
            ("faq", str(faq_id)),
            lambda source_id: CitationSource(
                source_id=source_id,
                cite_type="F",
                entity_id=_part(faq_id),
                page="",
                start="",
                end="",
                content=content,
                delivery_text=format_faqs([faq]),
            ),
        )

    def get(self, source_id: int) -> Optional[CitationSource]:
        with self._lock:
            return self._sources.get(source_id)

    def mark_delivered(self, text: str) -> None:
        """Record the sources whose id line and complete content are in ``text``.

        ``text`` is a message the model receives: a tool result after output limits, or the
        context of the turn. A source counts only when the complete text its tool prints for it
        follows its id line directly: slide and transcript text in its frame, an FAQ as a whole.
        A result cut inside that text does not count, and text inside a source that looks like
        an id line does not matter.
        """
        if not self._require_delivery or "Source id: [src:" not in text:
            return
        with self._lock:
            for match in _SOURCE_ID_LINE_RE.finditer(text):
                source_id = int(match.group(1))
                source = self._sources.get(source_id)
                if source is None or source_id in self._delivered:
                    continue
                if not source.delivery_text:
                    continue
                if text.startswith(source.delivery_text, match.end()):
                    self._delivered.add(source_id)

    def citable(self, source_id: int) -> Optional[CitationSource]:
        """The source, if the answer may cite it."""
        with self._lock:
            if self._require_delivery and source_id not in self._delivered:
                return None
            return self._sources.get(source_id)


def framed_content(text: str) -> str:
    """Slide or transcript text in the frame tools print it in after its id line."""
    return f"{CONTENT_OPEN}{text}{CONTENT_CLOSE}"


def source_id_line(source_id: Optional[int]) -> str:
    """The line a tool prints above citable content, or nothing for content without an id."""
    return "" if source_id is None else f"Source id: [src:{source_id}]\n"


def _map_prose(text: str, transform: Callable[[str], str]) -> str:
    """Apply ``transform`` to the text outside fenced and inline code."""
    parts: list[str] = []
    last = 0
    for match in _CODE_RE.finditer(text):
        parts.append(transform(text[last : match.start()]))  # noqa: E203
        parts.append(match.group(0))
        last = match.end()
    parts.append(transform(text[last:]))
    return "".join(parts)


def strip_cite_blocks(text: str) -> str:
    """Remove every cite block, including inside code (Artemis resolves them everywhere)."""
    return CITE_BLOCK_RE.sub("", text)


def strip_source_markers(text: str) -> str:
    """Remove source markers and cite blocks, e.g. from history, narration or MCQ fields."""
    text = strip_cite_blocks(text)

    def _strip(prose: str) -> str:
        prose = _MARKER_CHAIN_RE.sub("", prose)
        return _BROKEN_SOURCE_MARKER_RE.sub("", prose)

    return _map_prose(text, _strip)


def cited_source_ids(text: str, registry: CitationSourceRegistry) -> list[int]:
    """Ids of the citable sources cited outside code, in order of first use."""
    ids: list[int] = []

    def _collect(prose: str) -> str:
        for match in SOURCE_MARKER_RE.finditer(prose):
            source_id = int(match.group(1))
            if registry.citable(source_id) is not None and source_id not in ids:
                ids.append(source_id)
        return prose

    _map_prose(text, _collect)
    return ids


def render_citations(
    text: str,
    registry: CitationSourceRegistry,
    labels: Optional[dict[int, tuple[str, str]]] = None,
) -> str:
    """Turn the agent's markers into cite blocks.

    Cite blocks the agent wrote itself are removed everywhere. Outside code, each chain of
    markers becomes the cite blocks of its known sources, with repeats in the chain dropped;
    ids of unknown or not citable sources and broken markers disappear. Markers inside code stay untouched.
    """
    labels = labels or {}

    def _chain(match: re.Match) -> str:
        seen: list[int] = []
        for marker in SOURCE_MARKER_RE.finditer(match.group(0)):
            source_id = int(marker.group(1))
            if source_id in seen or registry.citable(source_id) is None:
                continue
            seen.append(source_id)
        if not seen:
            return ""
        blocks = " ".join(
            registry.citable(source_id).cite_block(*labels.get(source_id, ("", "")))
            for source_id in seen
        )
        return " " + blocks

    def _render(prose: str) -> str:
        prose = _MARKER_CHAIN_RE.sub(_chain, prose)
        return _BROKEN_SOURCE_MARKER_RE.sub("", prose)

    return _map_prose(strip_cite_blocks(text), _render)


def citation_free_draft(text: str) -> str:
    """Prepare a streamed draft: no markers and no cite blocks, as before markers existed.

    Artemis forwards drafts without checking material versions and reveals them character by
    character, so drafts never carry cite blocks; they appear with the final message. A draft
    end that may still grow into a marker or a cite block is held back until it is complete.
    """
    draft = strip_source_markers(text)
    code_spans = list(_CODE_RE.finditer(draft))
    if code_spans and code_spans[-1].end() == len(draft):
        return draft
    return _PENDING_MARKER_RE.sub("", draft)


def sources_for(
    registry: CitationSourceRegistry, source_ids: Iterable[int]
) -> list[CitationSource]:
    sources = [registry.get(source_id) for source_id in source_ids]
    return [source for source in sources if source is not None]

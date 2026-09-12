"""Deterministic quality assessment of ingested page chunks.

The verdict is computed from the chunk texts already in memory at the end of
a run, costs no LLM calls, and is deterministic on purpose: it feeds the
re-ingestion control loop, and a verdict that flaps between runs would make
that loop oscillate. The score and flags are stamped on the unit row and
reported by the ingestion census, so Artemis can requeue low-quality units
once per pipeline version and a re-run can compare its result against what
is already stored before replacing it.
"""

from collections import defaultdict

from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
)

# A page whose combined chunk text is shorter than this is considered thin:
# vision plus extraction produced next to nothing for it.
_THIN_PAGE_CHAR_THRESHOLD = 80

# Fraction of word-like characters below which a page's text is considered
# garbled (broken extraction, encoding damage, OCR noise).
_GARBLED_ALNUM_FRACTION = 0.5


def _alnum_fraction(text: str) -> float:
    stripped = "".join(text.split())
    if not stripped:
        return 0.0
    word_like = sum(1 for char in stripped if char.isalnum())
    return word_like / len(stripped)


def assess_page_chunks(chunks: list[dict]) -> tuple[float, list[str]]:
    """Score prepared page chunks; returns ``(score, flags)``.

    The score is the fraction of pages that are neither empty, thin, nor
    garbled, so 1.0 means every page holds substantial, readable text. Flags
    name the failing pages so an operator can judge the verdict.
    """
    if not chunks:
        return 0.0, ["no chunks"]

    text_by_page: dict[int, str] = defaultdict(str)
    for chunk in chunks:
        page_number = int(chunk[LectureUnitPageChunkSchema.PAGE_NUMBER.value])
        text_by_page[page_number] += chunk.get(
            LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value, ""
        )

    empty_pages: list[int] = []
    thin_pages: list[int] = []
    garbled_pages: list[int] = []
    for page_number in sorted(text_by_page):
        text = text_by_page[page_number].strip()
        if not text:
            empty_pages.append(page_number)
        elif len(text) < _THIN_PAGE_CHAR_THRESHOLD:
            thin_pages.append(page_number)
        elif _alnum_fraction(text) < _GARBLED_ALNUM_FRACTION:
            garbled_pages.append(page_number)

    flags: list[str] = []
    if empty_pages:
        flags.append(f"empty pages: {empty_pages}")
    if thin_pages:
        flags.append(f"thin pages: {thin_pages}")
    if garbled_pages:
        flags.append(f"garbled pages: {garbled_pages}")

    page_count = len(text_by_page)
    bad_count = len(empty_pages) + len(thin_pages) + len(garbled_pages)
    score = (page_count - bad_count) / page_count
    return round(score, 4), flags

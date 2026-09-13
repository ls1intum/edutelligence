"""Retrieval-time verbalization of SearchableEntities rows into text cards.

A cross-encoder and an answer LLM can only use what the text says: an entity
row whose due date lives in a structured property cannot answer "when is the
quiz due?" as far as either model can see (measured: bare titles score
0.05-0.07 on Qwen3-Reranker-8B, below the junk floor; rendered cards score
0.49-0.57 and carry the answer into the LLM context). Rendering happens per
request and never touches the stored entity, so the description display
contract is unaffected.
"""

from __future__ import annotations

from datetime import datetime, timezone

from iris.domain.search.global_search_dto import EntityCandidateDTO

_TYPE_LABEL = {
    "exercise": "Exercise",
    "lecture": "Lecture",
    "lecture_unit": "Lecture unit",
    "exam": "Exam",
    "faq": "FAQ",
    "channel": "Communication channel",
    "course": "Course",
    "post": "Post",
    "answer_post": "Post answer",
}

# Entity types whose bare card is a POINTER: it names material covering a
# topic without carrying the material itself.
_POINTER_TYPES = frozenset({"lecture", "lecture_unit", "exercise"})

# (attribute, verb) pairs rendered into the details line, in timeline order.
_DATE_FACTS = (
    ("visible_date", "visible from"),
    ("release_date", "released"),
    ("start_date", "starts"),
    ("due_date", "due"),
    ("end_date", "ends"),
    ("exam_visible_date", "visible from"),
    ("exam_start_date", "exam starts"),
    ("exam_end_date", "exam ends"),
)

_DESCRIPTION_MAX_CHARS = 800

_SECONDS_PER_MINUTE = 60


def _format_date(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).strftime("%A, %d %B %Y at %H:%M UTC")


def is_pointer_candidate(candidate: EntityCandidateDTO) -> bool:
    """A pointer card names material about a topic but holds no content."""
    return (
        candidate.entity_type in _POINTER_TYPES
        and not (candidate.description or "").strip()
    )


def render_entity_card(candidate: EntityCandidateDTO) -> str:
    """Verbalize one entity candidate. Always returns a non-empty string."""
    etype = candidate.entity_type
    label = _TYPE_LABEL.get(etype, etype.replace("_", " ").capitalize())
    title = (candidate.title or "").strip()

    head = f"{label}: {title!r}" if title else label
    if etype == "exercise" and candidate.exercise_type:
        head = f"{candidate.exercise_type.capitalize()} exercise: {title!r}"
    if candidate.course_name and etype != "course":
        head += f" in course {candidate.course_name.strip()!r}"
    parts = [head + "."]

    facts: list[str] = []
    for attribute, verb in _DATE_FACTS:
        formatted = _format_date(getattr(candidate, attribute))
        if formatted:
            facts.append(f"{verb} {formatted}")
    if candidate.max_points is not None:
        facts.append(f"worth {candidate.max_points:g} points")
    if candidate.quiz_duration_seconds:
        minutes = candidate.quiz_duration_seconds // _SECONDS_PER_MINUTE
        facts.append(f"quiz duration {minutes} minutes")
    if candidate.programming_language:
        facts.append(f"programming language {candidate.programming_language}")
    if candidate.short_name:
        facts.append(f"short name {candidate.short_name}")
    if etype == "channel":
        visibility = "public" if candidate.channel_is_public else "private"
        facts.append(f"a {visibility} discussion channel for messages and questions")
    if candidate.faq_state:
        facts.append(f"state {candidate.faq_state}")
    if candidate.unit_type:
        facts.append(f"unit type {candidate.unit_type}")
    if facts:
        parts.append("Details: " + "; ".join(facts) + ".")

    description = (candidate.description or "").strip()
    if description:
        parts.append(description[:_DESCRIPTION_MAX_CHARS])
    elif etype in _POINTER_TYPES:
        # A bare title does not read as "answers the topic" to the
        # cross-encoder even when the title names the topic exactly. Stating
        # the (always true) coverage relation lifts topical pointers without
        # inflating unrelated ones (measured: topical unit card 0.30 -> 0.40,
        # unrelated cards unchanged).
        noun = "exercise" if etype == "exercise" else "lecture"
        parts.append(
            f"The course materials in this {noun} cover the topic named in "
            "its title."
        )
    return "\n".join(parts)

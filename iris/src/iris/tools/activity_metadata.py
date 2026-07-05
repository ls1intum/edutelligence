from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

_MAX_DETAIL_CHARS = 120


@dataclass(frozen=True)
class ToolActivityMeta:
    detail_fn: Callable[[dict[str, Any] | None], str | None]
    result_fn: Callable[[Any], str | None]


def curate_detail(tool_name: str, inputs: dict[str, Any] | None) -> str | None:
    meta = ACTIVITY_METADATA.get(tool_name)
    if meta is None:
        return None
    return meta.detail_fn(inputs)


def curate_result(tool_name: str, output: Any) -> str | None:
    meta = ACTIVITY_METADATA.get(tool_name)
    if meta is None:
        return None
    return meta.result_fn(output)


def _truncate(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped[:_MAX_DETAIL_CHARS]


def _detail_from_fields(
    *field_names: str,
) -> Callable[[dict[str, Any] | None], str | None]:
    def detail(inputs: dict[str, Any] | None) -> str | None:
        if not inputs:
            return None
        for field_name in field_names:
            value = inputs.get(field_name)
            if isinstance(value, str):
                return _truncate(value)
        return None

    return detail


def _sequence_count(output: Any) -> int | None:
    if isinstance(output, (str, bytes, dict)):
        return None
    if isinstance(output, Sequence):
        return len(output)
    return None


def _count_string_markers(output: Any, marker: str) -> int | None:
    if not isinstance(output, str):
        return None
    count = output.count(marker)
    return count if count > 0 else None


def _lecture_result(output: Any) -> str | None:
    count = _sequence_count(output)
    if count is None:
        count = _count_string_markers(output, "Content:\n---")
    if count is None:
        return None
    return f"{count} sections"


def _faq_result(output: Any) -> str | None:
    count = _sequence_count(output)
    if count is None:
        count = _count_string_markers(output, "[FAQ ID:")
    if count is None:
        return None
    return f"{count} FAQs"


def _memory_result(output: Any) -> str | None:
    count = _sequence_count(output)
    if count is None:
        return None
    return f"{count} memories"


ACTIVITY_METADATA: dict[str, ToolActivityMeta] = {
    "lecture_content_retrieval": ToolActivityMeta(
        detail_fn=_detail_from_fields("query", "student_query", "input"),
        result_fn=_lecture_result,
    ),
    "faq_content_retrieval": ToolActivityMeta(
        detail_fn=_detail_from_fields("query", "student_query", "input"),
        result_fn=_faq_result,
    ),
    "memiris_search_for_memories": ToolActivityMeta(
        detail_fn=_detail_from_fields("query"),
        result_fn=_memory_result,
    ),
}

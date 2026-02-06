from __future__ import annotations

from typing import Iterable


def missing_llm_requirements(
    required: Iterable[str],
    *,
    available_ids: set[str],
) -> set[str]:
    return {r for r in required if r not in available_ids}


def format_llm_requirement(requirement: str) -> str:
    return requirement

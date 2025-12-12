from __future__ import annotations

from typing import Iterable

LLM_ID_PREFIX = "id:"


def llm_id_requirement(llm_id: str) -> str:
    return f"{LLM_ID_PREFIX}{llm_id}"


def _is_llm_id_requirement(requirement: str) -> bool:
    return requirement.startswith(LLM_ID_PREFIX)


def _strip_llm_id_prefix(requirement: str) -> str:
    return requirement.removeprefix(LLM_ID_PREFIX)


def missing_llm_requirements(
    required: Iterable[str],
    *,
    available_models: set[str],
    available_ids: set[str],
) -> set[str]:
    missing: set[str] = set()
    for requirement in required:
        if _is_llm_id_requirement(requirement):
            if _strip_llm_id_prefix(requirement) not in available_ids:
                missing.add(requirement)
        else:
            if requirement not in available_models:
                missing.add(requirement)
    return missing


def format_llm_requirement(requirement: str) -> str:
    if _is_llm_id_requirement(requirement):
        return f"{_strip_llm_id_prefix(requirement)} (id)"
    return requirement

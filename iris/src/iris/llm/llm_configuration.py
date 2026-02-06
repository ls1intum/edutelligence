from __future__ import annotations

from typing import Literal, Mapping, Sequence

from iris.config import settings

Environment = Literal["local", "cloud"]


class LlmConfigurationError(ValueError):
    """Raised when llm_configuration is missing or invalid."""


# pipeline_id -> variant_id -> required roles
REQUIRED_LLM_CONFIGURATION: dict[str, dict[str, set[str]]] = {
    "exercise_chat_pipeline": {
        "default": {"chat"},
        "advanced": {"chat"},
    },
    "course_chat_pipeline": {
        "default": {"chat"},
        "advanced": {"chat"},
    },
    "lecture_chat_pipeline": {
        "default": {"chat"},
        "advanced": {"chat"},
    },
    "text_exercise_chat_pipeline": {
        "default": {"chat"},
        "advanced": {"chat"},
    },
    "tutor_suggestion_pipeline": {
        "default": {"chat"},
        "advanced": {"chat"},
    },
    "competency_extraction_pipeline": {
        "default": {"chat"},
    },
    "inconsistency_check_pipeline": {
        "default": {"solver", "prettify"},
    },
    "rewriting_pipeline": {
        "faq": {"rewriting", "consistency"},
        "problem_statement": {"rewriting", "consistency"},
    },
    "lecture_unit_page_ingestion_pipeline": {
        "default": {"chat", "embedding"},
        "advanced": {"chat", "embedding"},
    },
    "faq_ingestion_pipeline": {
        "default": {"chat", "embedding"},
    },
    "transcription_ingestion_pipeline": {
        "default": {"chat", "embedding"},
    },
    "lecture_unit_segment_summary_pipeline": {
        "default": {"chat", "embedding"},
    },
    "lecture_unit_summary_pipeline": {
        "default": {"chat"},
    },
    "lecture_unit_pipeline": {
        "default": {"embedding"},
    },
    "lecture_retrieval_pipeline": {
        "default": {"chat", "embedding", "reranker"},
    },
    "lecture_unit_segment_retrieval_pipeline": {
        "default": {"chat", "embedding", "reranker"},
    },
    "lecture_transcriptions_retrieval_pipeline": {
        "default": {"chat", "embedding", "reranker"},
    },
    "faq_retrieval_pipeline": {
        "default": {"chat", "embedding"},
    },
    "citation_pipeline": {
        "default": {"chat"},
        "advanced": {"chat"},
    },
    "interaction_suggestion_pipeline": {
        "course": {"chat"},
        "exercise": {"chat"},
    },
    "session_title_generation_pipeline": {
        "default": {"chat"},
    },
    "code_feedback_pipeline": {
        "default": {"chat"},
    },
    "summary_pipeline": {
        "default": {"chat"},
    },
}


def validate_llm_configuration(
    config: Mapping[str, Mapping[str, Mapping[str, Mapping[str, str]]]] | None = None,
    required: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
) -> None:
    """
    Validate that llm_configuration contains all required pipeline/variant/role/local-cloud entries.
    Raises LlmConfigurationError if anything is missing.
    """
    cfg = config or settings.llm_configuration
    required = required or REQUIRED_LLM_CONFIGURATION
    missing: list[str] = []

    for pipeline_id, variants in required.items():
        pipeline_cfg = cfg.get(pipeline_id)
        if not pipeline_cfg:
            missing.append(f"llm_configuration.{pipeline_id}")
            continue

        for variant_id, roles in variants.items():
            variant_cfg = pipeline_cfg.get(variant_id)
            if not variant_cfg:
                missing.append(f"llm_configuration.{pipeline_id}.{variant_id}")
                continue

            for role in roles:
                role_cfg = variant_cfg.get(role)
                if not role_cfg:
                    missing.append(
                        f"llm_configuration.{pipeline_id}.{variant_id}.{role}"
                    )
                    continue

                environments = (
                    ("cloud",) if not settings.local_llm_enabled else ("local", "cloud")
                )
                for env in environments:
                    value = role_cfg.get(env)
                    if not value or not isinstance(value, str):
                        missing.append(
                            f"llm_configuration.{pipeline_id}.{variant_id}.{role}.{env}"
                        )

    if missing:
        raise LlmConfigurationError(
            "Missing llm configuration entries:\n" + "\n".join(missing)
        )


def is_local_llm_enabled() -> bool:
    """Return whether local LLM support is enabled."""
    return settings.local_llm_enabled


def resolve_model(pipeline_id: str, variant_id: str, role: str, *, local: bool) -> str:
    if local and not settings.local_llm_enabled:
        local = False
    env: Environment = "local" if local else "cloud"
    try:
        role_cfg = settings.llm_configuration[pipeline_id][variant_id][role]
        model = role_cfg[env]
    except KeyError as e:
        raise LlmConfigurationError(
            f"Missing llm_configuration.{pipeline_id}.{variant_id}.{role}.{env}"
        ) from e

    if not model or not isinstance(model, str):
        raise LlmConfigurationError(
            f"Invalid llm_configuration.{pipeline_id}.{variant_id}.{role}.{env}"
        )
    return model


def resolve_role_models(
    pipeline_id: str, variant_id: str, role: str
) -> dict[Environment, str]:
    return {
        "local": resolve_model(pipeline_id, variant_id, role, local=True),
        "cloud": resolve_model(pipeline_id, variant_id, role, local=False),
    }


def role_requirements(pipeline_id: str, variant_id: str, role: str) -> set[str]:
    """
    Return the LLM ID requirements for a given pipeline/variant/role.

    Values are matched against ``LanguageModel.id``.
    """
    models = resolve_role_models(pipeline_id, variant_id, role)
    return {models["local"], models["cloud"]}

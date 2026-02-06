from __future__ import annotations

from typing import Literal, Mapping

from iris.config import settings

Environment = Literal["local", "cloud"]


class LlmConfigurationError(ValueError):
    """Raised when llm_configuration is missing or invalid."""


def validate_llm_configuration(
    config: Mapping[str, Mapping[str, Mapping[str, Mapping[str, str]]]] | None = None,
) -> None:
    """
    Validate structural completeness of llm_configuration.

    Walks every pipeline/variant/role entry in the config and checks that
    each role has valid local (if enabled) and cloud model IDs.
    Raises LlmConfigurationError if anything is missing.
    """
    cfg = config or settings.llm_configuration
    missing: list[str] = []

    for pipeline_id, variants in cfg.items():
        if not isinstance(variants, dict):
            missing.append(f"llm_configuration.{pipeline_id} (not a mapping)")
            continue

        for variant_id, roles in variants.items():
            if not isinstance(roles, dict):
                missing.append(
                    f"llm_configuration.{pipeline_id}.{variant_id} (not a mapping)"
                )
                continue

            for role, role_cfg in roles.items():
                if not isinstance(role_cfg, dict):
                    missing.append(
                        f"llm_configuration.{pipeline_id}.{variant_id}.{role} (not a mapping)"
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

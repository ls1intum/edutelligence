import importlib
from typing import Any, Optional, Type, TypeVar, cast

from pydantic import BaseModel

from athena.logger import logger
from athena.module_config import is_explicit_module_config
from athena.schemas.ai_selection import AiSelectionDecision
from llm_core.models.llm_config import LLMConfig
from llm_core.models.model_config import ModelConfig

_LOCAL_MODEL_ENV = "LLM_LOCAL_MODEL"

B = TypeVar("B", bound=BaseModel)

def resolve_ai_selection(selection: AiSelectionDecision | str | None) -> AiSelectionDecision:
    if selection is None:
        return AiSelectionDecision.CLOUD_AI

    if isinstance(selection, AiSelectionDecision):
        return selection

    try:
        return AiSelectionDecision(selection)
    except ValueError:
        logger.warning(
            "Received unsupported AI selection '%s'. Falling back to %s.",
            selection,
            AiSelectionDecision.CLOUD_AI.value,
        )
        return AiSelectionDecision.CLOUD_AI


def module_uses_llm(
    module_config: Optional[BaseModel] = None,
    module_config_type: Optional[Type[BaseModel]] = None,
) -> bool:
    config_type = module_config_type or (type(module_config) if module_config is not None else None)
    if config_type is None:
        return False

    config_module = importlib.import_module(config_type.__module__)
    return getattr(config_module, "llm_config", None) is not None


def _replace_model_configs(value: Any, replacement_model: ModelConfig) -> Any:
    if isinstance(value, ModelConfig):
        return replacement_model

    if isinstance(value, BaseModel):
        updates: dict[str, Any] = {}
        for field_name in value.__class__.model_fields:
            current_value = getattr(value, field_name)
            updated_value = _replace_model_configs(current_value, replacement_model)
            if updated_value is not current_value:
                updates[field_name] = updated_value
        return value.model_copy(update=updates) if updates else value

    if isinstance(value, list):
        updated_items = [_replace_model_configs(item, replacement_model) for item in value]
        return updated_items if any(new is not old for old, new in zip(value, updated_items)) else value

    if isinstance(value, tuple):
        updated_items = tuple(_replace_model_configs(item, replacement_model) for item in value)
        return updated_items if any(new is not old for old, new in zip(value, updated_items)) else value

    if isinstance(value, dict):
        updated_items = {key: _replace_model_configs(item, replacement_model) for key, item in value.items()}
        return updated_items if any(updated_items[key] is not value[key] for key in value) else value

    return value


def apply_ai_selection_to_module_config(
    module_config: B,
    llm_config: LLMConfig,
    selection: AiSelectionDecision | str | None,
) -> B | None:
    if is_explicit_module_config(module_config):
        return module_config

    resolved_selection = resolve_ai_selection(selection)
    if resolved_selection == AiSelectionDecision.NO_AI:
        return None

    if resolved_selection == AiSelectionDecision.CLOUD_AI:
        return module_config

    replacement_model = llm_config.models.local_model_config
    if replacement_model is None:
        logger.warning(
            "No LOCAL_AI model configured for the requested AI selection. "
            "Set %s to a local model identifier such as logos_*, ollama_*, or lmstudio_*.",
            _LOCAL_MODEL_ENV,
        )
        return None

    return cast(B, _replace_model_configs(module_config, replacement_model))


def resolve_module_config_for_selection(
    module_config: Optional[BaseModel],
    selection: AiSelectionDecision | str | None,
) -> Optional[BaseModel]:
    if module_config is None or is_explicit_module_config(module_config):
        return module_config

    if not module_uses_llm(module_config=module_config):
        return module_config

    config_module = importlib.import_module(type(module_config).__module__)
    llm_config = getattr(config_module, "llm_config")

    return apply_ai_selection_to_module_config(module_config, llm_config, selection)

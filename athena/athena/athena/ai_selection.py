import importlib
from contextlib import AbstractContextManager
from typing import Callable, Optional, Type, cast

from pydantic import BaseModel

from athena.logger import logger
from athena.schemas.ai_selection import AiSelectionDecision


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


def _get_llm_core_helper(name: str) -> Callable[..., object]:
    model_selection_module = importlib.import_module("llm_core.utils.model_selection")
    return getattr(model_selection_module, name)


def local_ai_selection_available() -> bool:
    helper = _get_llm_core_helper("local_ai_selection_available")
    return bool(helper())


def get_local_ai_configuration_error_message() -> str:
    helper = _get_llm_core_helper("get_local_ai_configuration_error_message")
    return str(helper())


def llm_ai_selection_context(selection: AiSelectionDecision | None) -> AbstractContextManager[object]:
    helper = _get_llm_core_helper("ai_selection_context")
    return cast(AbstractContextManager[object], helper(selection))

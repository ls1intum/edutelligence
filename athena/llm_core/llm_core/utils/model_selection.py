import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from athena.schemas import AiSelectionDecision
from llm_core.models.model_config import ModelConfig
from llm_core.utils.model_factory import create_config_for_model

_LOCAL_MODEL_ENV = "LLM_LOCAL_MODEL"
_current_ai_selection: ContextVar[AiSelectionDecision | None] = ContextVar(
    "llm_core_current_ai_selection",
    default=None,
)


class LocalAISelectionConfigurationError(RuntimeError):
    pass


@contextmanager
def ai_selection_context(selection: AiSelectionDecision | None) -> Iterator[None]:
    token = _current_ai_selection.set(selection)
    try:
        yield
    finally:
        _current_ai_selection.reset(token)


def get_current_ai_selection() -> AiSelectionDecision | None:
    return _current_ai_selection.get()


def get_local_ai_configuration_error_message() -> str:
    return (
        "No LOCAL_AI model is configured in Athena. "
        "Set LLM_LOCAL_MODEL to a local model identifier such as logos_*, "
        "ollama_*, or lmstudio_*."
    )


def get_local_model_config() -> ModelConfig:
    local_model_name = os.getenv(_LOCAL_MODEL_ENV)
    if not local_model_name:
        raise LocalAISelectionConfigurationError(get_local_ai_configuration_error_message())

    try:
        return create_config_for_model(local_model_name)
    except ValueError as exc:
        raise LocalAISelectionConfigurationError(
            get_local_ai_configuration_error_message()
        ) from exc


def local_ai_selection_available() -> bool:
    try:
        get_local_model_config()
        return True
    except LocalAISelectionConfigurationError:
        return False


def get_selected_model(model: ModelConfig) -> ModelConfig:
    if get_current_ai_selection() == AiSelectionDecision.LOCAL_AI:
        return get_local_model_config()
    return model

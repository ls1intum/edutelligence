from llm_core.models.llm_config import LLMConfig, LLMConfigModel, RawLLMConfig
from llm_core.utils.model_factory import create_config_for_model, ModelFactories
from typing import Dict, Optional

_state: Dict[str, Optional[LLMConfig]] = {"llm_config": None}


def get_llm_config(raw_config: Dict, factories: ModelFactories) -> LLMConfig:
    """
    Materializes the LLMConfig from raw dict (loaded via providers.Configuration).
    Caches the result.
    """
    # Here we read/write _state["llm_config"] without using 'global'.
    if _state["llm_config"] is None:
        raw_llm = RawLLMConfig(**raw_config)  # Validate with Pydantic
        _state["llm_config"] = _materialize_llm_config(raw_llm, factories)

    return _state["llm_config"]


def _materialize_llm_config(
    raw_config: RawLLMConfig, factories: ModelFactories
) -> LLMConfig:
    base_model = raw_config.models.base_model
    if not base_model:
        raise ValueError("Missing required 'base_model' in models")

    models_obj = LLMConfigModel(
        base_model_config=create_config_for_model(base_model, factories),
        mini_model_config=(
            create_config_for_model(raw_config.models.mini_model, factories)
            if raw_config.models.mini_model
            else None
        ),
        fast_reasoning_model_config=(
            create_config_for_model(raw_config.models.fast_reasoning_model, factories)
            if raw_config.models.fast_reasoning_model
            else None
        ),
        long_reasoning_model_config=(
            create_config_for_model(raw_config.models.long_reasoning_model, factories)
            if raw_config.models.long_reasoning_model
            else None
        ),
    )

    return LLMConfig(models=models_obj)

from llm_core.models.llm_config import LLMConfig, LLMConfigModel, RawLLMConfig
from llm_core.utils.model_factory import create_config_for_model
import yaml
from pathlib import Path
from typing import Dict, Optional

_state: Dict[str, Optional[LLMConfig]] = {"llm_config": None}

def _load_raw_llm_config(path: Optional[str] = None) -> RawLLMConfig:
    """
    Loads the LLM configuration from a YAML file and returns a validated LLMConfig.
    Raises pydantic.ValidationError if something is incorrect in the YAML.
    """
    # By default, we assume 'llm_config.yml' is in the same directory
    if path is None:
        path = "llm_config.yml"

    config_path = Path(path).resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"LLM config file not found at: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        raw_data = yaml.safe_load(f)

    # Validate and parse the Pydantic model
    return RawLLMConfig(**raw_data)

def _materialize_llm_config(raw_config: RawLLMConfig) -> LLMConfig:
    base_model = raw_config.models.base_model
    if not base_model:
        raise ValueError("Missing required 'base_model' in models")
    
    models_obj = LLMConfigModel(
        base_model_config=create_config_for_model(base_model),
        mini_model_config=(
            create_config_for_model(raw_config.models.mini_model)
            if raw_config.models.mini_model
            else None
        ),
        fast_reasoning_model_config=(
            create_config_for_model(raw_config.models.fast_reasoning_model)
            if raw_config.models.fast_reasoning_model
            else None
        ),
        long_reasoning_model_config=(
            create_config_for_model(raw_config.models.long_reasoning_model)
            if raw_config.models.long_reasoning_model
            else None
        ),
    )

    return LLMConfig(models=models_obj)

def get_llm_config(path: Optional[str] = None) -> LLMConfig:
    """
    Public function: returns a cached LLMConfig instance. 
    If not loaded yet, loads from YAML and materializes it. 
    """
    # Here we read/write _state["llm_config"] without using 'global'.
    if _state["llm_config"] is None:
        raw_config = _load_raw_llm_config(path)
        _state["llm_config"] = _materialize_llm_config(raw_config)

    return _state["llm_config"]
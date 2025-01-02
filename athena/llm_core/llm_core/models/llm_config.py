from pydantic import BaseModel
from typing import Optional
from llm_core.models.model_config import ModelConfig

class RawModelsSection(BaseModel):
    base_model: Optional[str]
    mini_model: Optional[str]
    fast_reasoning_model: Optional[str]
    long_reasoning_model: Optional[str]

class RawLLMConfig(BaseModel):
    models: RawModelsSection

class LLMConfigModel(BaseModel):
    base_model_config: ModelConfig
    mini_model_config: Optional[ModelConfig]
    fast_reasoning_model_config: Optional[ModelConfig]
    long_reasoning_model_config: Optional[ModelConfig]

class LLMConfig(BaseModel):
    models: LLMConfigModel
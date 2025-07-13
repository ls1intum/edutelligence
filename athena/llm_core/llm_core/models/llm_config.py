from pydantic import BaseModel
from typing import Optional
from . import ModelConfigType


class RawModelsSection(BaseModel):
    base_model: Optional[str]
    mini_model: Optional[str]
    fast_reasoning_model: Optional[str]
    long_reasoning_model: Optional[str]


class RawLLMConfig(BaseModel):
    models: RawModelsSection


class LLMConfigModel(BaseModel):
    base_model_config: ModelConfigType
    mini_model_config: Optional[ModelConfigType]
    fast_reasoning_model_config: Optional[ModelConfigType]
    long_reasoning_model_config: Optional[ModelConfigType]


class LLMConfig(BaseModel):
    models: LLMConfigModel

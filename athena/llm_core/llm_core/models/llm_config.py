from pydantic import BaseModel
from typing import Optional
from . import ModelConfigType


class RawModelsSection(BaseModel):
    base_model: Optional[str] = None
    mini_model: Optional[str] = None
    fast_reasoning_model: Optional[str] = None
    long_reasoning_model: Optional[str] = None


class RawLLMConfig(BaseModel):
    models: RawModelsSection


class LLMConfigModel(BaseModel):
    base_model_config: ModelConfigType
    mini_model_config: Optional[ModelConfigType] = None
    fast_reasoning_model_config: Optional[ModelConfigType] = None
    long_reasoning_model_config: Optional[ModelConfigType] = None


class LLMConfig(BaseModel):
    models: LLMConfigModel

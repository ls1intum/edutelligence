"""Validated settings for the next benchmark, independent of stored results."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ServingOverrides(BaseModel):
    """Only vLLM settings supported by the benchmark editor may be overridden."""

    model_config = ConfigDict(extra="forbid")
    tensor_parallel_size: int | None = Field(default=None, ge=1, le=64)
    pipeline_parallel_size: int | None = Field(default=None, ge=1, le=64)
    kv_cache_dtype: Literal["auto", "fp8", "fp8_e4m3", "fp8_e5m2"] | None = None
    kv_cache_memory_bytes: str | None = Field(
        default=None, max_length=32, pattern=r"^(?:[0-9]+(?:[.][0-9]+)?[KMGTPkmgpt]?[iI]?[bB]?)?$"
    )
    max_num_seqs: int | None = Field(default=None, ge=0, le=65536)
    max_num_batched_tokens: int | None = Field(default=None, gt=0)
    enable_prefix_caching: bool | None = None
    max_model_len: int | None = Field(default=None, ge=0)
    gpu_memory_utilization: float | None = Field(default=None, ge=0.1, le=1)
    quantization: str | None = Field(default=None, max_length=64, pattern=r"^[a-zA-Z0-9_.-]*$")
    dtype: Literal["auto", "float16", "bfloat16", "float32", "half", "float"] | None = None
    enforce_eager: bool | None = None
    disable_custom_all_reduce: bool | None = None
    hf_overrides: dict | None = None


class BenchmarkSettings(BaseModel):
    """Public text datasets and reproducible GuideLLM run settings."""

    dataset: str = Field(default="openai/gsm8k", max_length=200, pattern=r"^[\w.-]+/[\w.-]+$")
    subset: str = Field(default="main", min_length=1, max_length=200)
    split: str = Field(default="test", min_length=1, max_length=100, pattern=r"^[\w.-]+$")
    text_column: str = Field(default="question", min_length=1, max_length=200)
    profile: Literal["synchronous", "concurrent"] = "synchronous"
    concurrency: int = Field(default=1, ge=1, le=32)
    seed: int = Field(default=42, ge=0, le=2147483647)
    serving_overrides: ServingOverrides = Field(default_factory=ServingOverrides)

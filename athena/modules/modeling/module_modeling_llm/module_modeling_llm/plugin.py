from fastapi import FastAPI
from athena.schemas.exercise_type import ExerciseType
from llm_core.models.llm_config import LLMConfig
from .config import Configuration, BasicApproachConfig


class ModelingPlugin:
    exercise_type = ExerciseType.modeling
    config_cls = Configuration

    def build_default_config(self, llm: LLMConfig) -> Configuration:
        approach = BasicApproachConfig(
            generate_feedback=llm.models.base_model_config,
            filter_feedback=llm.models.mini_model_config
            or llm.models.base_model_config,
            review_feedback=llm.models.fast_reasoning_model_config
            or llm.models.base_model_config,
            generate_grading_instructions=llm.models.long_reasoning_model_config
            or llm.models.base_model_config,
        )
        return Configuration(approach=approach)

    def register_routes(self, app: FastAPI) -> None:
        from .endpoints import suggest_feedback  # noqa: F401

    def warm_start(self) -> None:
        import nltk, tiktoken

        try:
            nltk.data.find("tokenizers/punkt")
        except LookupError:
            nltk.download("punkt")
        tiktoken.get_encoding("cl100k_base")

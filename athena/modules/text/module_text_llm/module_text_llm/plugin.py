from fastapi import FastAPI
from athena.schemas.exercise_type import ExerciseType
from llm_core.models.llm_config import LLMConfig

from .config import Configuration
from module_text_llm.basic_approach import BasicApproachConfig


class TextPlugin:
    exercise_type = ExerciseType.text
    config_cls = Configuration

    def build_default_config(self, llm: LLMConfig) -> Configuration:
        # Default to Basic approach; others can still be selected via config.
        approach = BasicApproachConfig(model=llm.models.base_model_config)
        return Configuration(approach=approach)

    def register_routes(self, app: FastAPI) -> None:
        # Import side-effect registers all decorated endpoints/consumers.
        from .endpoints import (  # noqa: F401
            receive_submissions,
            select_submission,
            process_incoming_feedback,
            suggest_feedback,
            evaluate_feedback,
        )

    def warm_start(self) -> None:
        import nltk, tiktoken

        try:
            nltk.data.find("tokenizers/punkt")
        except LookupError:
            nltk.download("punkt")
        tiktoken.get_encoding("cl100k_base")

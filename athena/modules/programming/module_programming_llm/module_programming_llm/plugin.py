from fastapi import FastAPI
from athena.schemas.exercise_type import ExerciseType
from llm_core.models.llm_config import LLMConfig

from .config import (
    Configuration,
    GradedBasicApproachConfig,
    NonGradedBasicApproachConfig,
)


class ProgrammingPlugin:
    exercise_type = ExerciseType.programming
    config_cls = Configuration

    def build_default_config(self, llm: LLMConfig) -> Configuration:
        # Default to Basic approach with separate graded/non-graded configs
        graded_approach = GradedBasicApproachConfig(model=llm.models.base_model_config)
        non_graded_approach = NonGradedBasicApproachConfig(
            model=llm.models.base_model_config
        )
        return Configuration(
            graded_approach=graded_approach, non_graded_approach=non_graded_approach
        )

    def register_routes(self, app: FastAPI) -> None:
        # Import side-effect registers all decorated endpoints/consumers.
        from .endpoints import (  # noqa: F401
            receive_submissions,
            select_submission,
            process_incoming_feedback,
            suggest_feedback,
        )

    def warm_start(self) -> None:
        import tiktoken

        # Preload for token estimation later
        tiktoken.get_encoding("cl100k_base")

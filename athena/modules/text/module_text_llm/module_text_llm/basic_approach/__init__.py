from pydantic import Field
from typing import Literal
from athena.text import Exercise, Submission
from module_text_llm.approach_config import ApproachConfig
from module_text_llm.basic_approach.prompt_generate_suggestions import (
    GenerateSuggestionsPrompt,
)


class BasicApproachConfig(ApproachConfig):
    type: Literal["basic"] = "basic"
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(
        default=GenerateSuggestionsPrompt()
    )

    async def generate_suggestions(
        self,
        exercise: Exercise,
        submission: Submission,
        config,
        *,
        debug: bool,
        is_graded: bool
    ):
        from module_text_llm.basic_approach.generate_suggestions import (
            generate_suggestions,
        )  # pylint: disable=import-outside-toplevel

        return await generate_suggestions(
            exercise, submission, config, debug, is_graded
        )

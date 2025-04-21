from module_text_llm.approach_config import ApproachConfig
from typing import Literal
from athena.text import Exercise, Submission
from module_text_llm.divide_and_conquer.generate_suggestions import generate_suggestions

class DivideAndConquerConfig(ApproachConfig):
    type: Literal['divide_and_conquer'] = 'divide_and_conquer'
    # Prompts are generated at run time.
    async def generate_suggestions(self, exercise: Exercise, submission: Submission, config,*, debug: bool, is_graded: bool):
        return await generate_suggestions(exercise, submission, config, debug, is_graded)
    
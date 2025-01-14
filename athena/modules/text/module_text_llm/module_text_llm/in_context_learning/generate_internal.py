from typing import List
from module_text_llm.approach_config import ApproachConfig

from athena import emit_meta
from athena.text import Exercise, Feedback
from llm_core.utils.llm_utils import (
    get_chat_prompt_with_formatting_instructions
)
from llm_core.utils.predict_and_parse import predict_and_parse
from module_text_llm.helpers.utils import format_grading_instructions
from module_text_llm.in_context_learning.prompt_internal import InternalGradingInstructions
from module_text_llm.in_context_learning.prompt_internal import system_message, human_message
async def generate(exercise: Exercise, config: ApproachConfig, debug: bool) -> List[Feedback]:

    model = config.model.get_model()  # type: ignore[attr-defined]
    prompt_input = {
        "max_points": exercise.max_points,
        "bonus_points": exercise.bonus_points,
        "grading_instructions": format_grading_instructions(exercise.grading_instructions, exercise.grading_criteria),
        "problem_statement": exercise.problem_statement or "No problem statement.",
        "example_solution": exercise.example_solution,
    }

    chat_prompt = get_chat_prompt_with_formatting_instructions(
        model=model, 
        system_message=system_message, 
        human_message=human_message, 
        pydantic_object=InternalGradingInstructions
    )
    
    result = await predict_and_parse(
        model=model, 
        chat_prompt=chat_prompt, 
        prompt_input=prompt_input, 
        pydantic_object=InternalGradingInstructions,
        tags=[
            f"exercise-{exercise.id}",
        ],
        use_function_calling=True
    )

    if debug:
        emit_meta("generate_suggestions", {
            "prompt": chat_prompt.format(**prompt_input),
            "result": result.dict() if result is not None else None
        })

    if result is None:
        return []

    return result

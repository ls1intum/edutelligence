from typing import List

from athena import emit_meta
from athena.text import Exercise, Submission, Feedback
from athena.logger import logger
from llm_core.utils.llm_utils import (
    get_chat_prompt_with_formatting_instructions
)
import os
import json
from llm_core.utils.predict_and_parse import predict_and_parse
from module_text_llm.helpers.utils import add_sentence_numbers,format_grading_instructions
from module_text_llm.in_context_learning.prompt_internal import InternalGradingInstructions
from module_text_llm.in_context_learning.prompt_internal import system_message_upgrade, human_message_upgrade
from module_text_llm.helpers.get_internal_sgi import get_internal_sgi, write_internal_sgi, extract_text_from_reference
from module_text_llm.in_context_learning import InContextLearningConfig
async def update_grading_instructions(exercise: Exercise, feedbacks:List[Feedback], submission : Submission) -> List[Feedback]:

    logger.info("Generating updated internal SGI")
    debug = True
    iSGI = get_internal_sgi()
    ex_id = str(exercise.id)   
    if(ex_id not in iSGI):
        logger.info("Not in iSGI")
        return []
    internal_instructions = iSGI[ex_id]
    # We get the internal SGI
    config = InContextLearningConfig()
    model = config.model.get_model()  # type: ignore[attr-defined]
    prompt_input = {
        "max_points": exercise.max_points,
        "bonus_points": exercise.bonus_points,
        "internal_SGI": str(internal_instructions),
        "grading_instructions": format_grading_instructions(exercise.grading_instructions, exercise.grading_criteria),
        "problem_statement": exercise.problem_statement or "No problem statement.",
        "example_solution": exercise.example_solution,
        "feedbacks" : extract_text_from_reference(exercise.id,submission, feedbacks), # Model suggestion TODO get the exact text from the submission
        "submission": add_sentence_numbers(submission.text)
    }

    chat_prompt = get_chat_prompt_with_formatting_instructions(
        model=model, 
        system_message=system_message_upgrade, 
        human_message=human_message_upgrade, 
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
        print("result was none")
        return []
    
    iSGI[ex_id] = result.dict()
    write_internal_sgi(exercise.id, iSGI)
    return result

# from typing import List

# from athena import emit_meta
# from athena.text import Exercise, Submission, Feedback
# from athena.logger import logger
# from llm_core.utils.llm_utils import (
#     get_chat_prompt_with_formatting_instructions, 
#     check_prompt_length_and_omit_features_if_necessary, 
#     num_tokens_from_prompt,
# )
# import os
# import json
# from llm_core.utils.predict_and_parse import predict_and_parse
# from module_text_llm.config import CrazyApproachConfig
# from module_text_llm.helpers.utils import add_sentence_numbers, get_index_range_from_line_range, format_grading_instructions
# from module_text_llm.in_context_learning.prompt_internal import InternalGradingInstructions
# from module_text_llm.in_context_learning.prompt_internal import system_message, human_message
# async def generate(exercise: Exercise, config: CrazyApproachConfig, debug: bool) -> List[Feedback]:

# # What do we need to do here. We need to give the existing internal grading instructions
# # together with the exercise data and the new suggestions. We ened to think about the structure
# # of how the updated instructions look like.
# # Do we want to provide examples of assessments?
#     model = config.model.get_model()  # type: ignore[attr-defined]
#     prompt_input = {
#         "max_points": exercise.max_points,
#         "bonus_points": exercise.bonus_points,
# # We will no longer send the exercise grading instructions but rather the internal SGI
#         "internal_SGI": [],
#         #"grading_instructions": format_grading_instructions(exercise.grading_instructions, exercise.grading_criteria),
#         "problem_statement": exercise.problem_statement or "No problem statement.",
#         "example_solution": exercise.example_solution,
#         "suggestion" : [], # Model suggestion
#         "adapted_suggestion" : [], # Tutor adapated suggestion
#         # "submission": add_sentence_numbers(submission.text)
#     }
# # Additionally, we have to send the suggested feedback along with the adjustment.
#     chat_prompt = get_chat_prompt_with_formatting_instructions(
#         model=model, 
#         system_message=system_message, 
#         human_message=human_message, 
#         pydantic_object=InternalGradingInstructions
#     )
    
#     result = await predict_and_parse(
#         model=model, 
#         chat_prompt=chat_prompt, 
#         prompt_input=prompt_input, 
#         pydantic_object=InternalGradingInstructions,
#         tags=[
#             f"exercise-{exercise.id}",
#         ],
#         use_function_calling=True
#     )

#     if debug:
#         emit_meta("generate_suggestions", {
#             "prompt": chat_prompt.format(**prompt_input),
#             "result": result.dict() if result is not None else None
#         })

#     if result is None:
#         return []

#     return result

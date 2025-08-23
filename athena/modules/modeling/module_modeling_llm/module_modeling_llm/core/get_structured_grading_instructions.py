import hashlib
import json
from typing import List, Optional
from athena.metadata import emit_meta
from athena.storage.structured_grading_criterion_storage import get_structured_grading_criterion, store_structured_grading_criterion
from langchain_core.prompts import ChatPromptTemplate

from athena.schemas import GradingCriterion, StructuredGradingCriterion
from llm_core.core.predict_and_parse import predict_and_parse
from module_modeling_llm.config import BasicApproachConfig
from module_modeling_llm.models.exercise_model import ExerciseModel
from module_modeling_llm.prompts.structured_grading_instructions_prompt import StructuredGradingInstructionsInputs

async def get_structured_grading_instructions(
        exercise_model: ExerciseModel,
        config: BasicApproachConfig,
        grading_instructions: Optional[str],
        grading_criteria: Optional[List[GradingCriterion]],
        debug: bool
) -> StructuredGradingCriterion:
    
    if grading_criteria:
        return StructuredGradingCriterion(criteria=grading_criteria)
    
    # Check if we have cached instructions for this exercise
    current_hash = get_grading_instructions_hash(exercise_model)
    cached_instructions = get_structured_grading_criterion(exercise_model.exercise_id, current_hash)
    if cached_instructions:
        print("Using cached instructions")
        return cached_instructions

    chat_prompt = ChatPromptTemplate.from_messages([
        ("system", config.generate_suggestions_prompt.structured_grading_instructions_system_message),
        ("human", config.generate_suggestions_prompt.structured_grading_instructions_human_message)])
    
    prompt_inputs = StructuredGradingInstructionsInputs(
            problem_statement=exercise_model.problem_statement or "No problem statement.",
            max_points=exercise_model.max_points,
            bonus_points=exercise_model.bonus_points,
            grading_instructions=grading_instructions or "No grading instructions.",
            submission_uml_type=exercise_model.submission_uml_type,
            example_solution=exercise_model.transformed_example_solution or "No example solution.",
        )

    grading_instruction_result = await predict_and_parse(
        model=config.generate_grading_instructions,
        chat_prompt=chat_prompt,
        prompt_input=prompt_inputs.model_dump(),
        pydantic_object=StructuredGradingCriterion,
        tags=[
            f"exercise-{exercise_model.exercise_id}",
            f"submission-{exercise_model.submission_id}",
        ]
    )

    if debug:
        emit_meta("get_structured_grading_instructions", {
            "prompt": chat_prompt.format(**prompt_inputs.model_dump()),
            "result": grading_instruction_result.model_dump() if grading_instruction_result is not None else None
        })

    if not grading_instruction_result:
        raise ValueError("No structured grading instructions were returned by the model.")
    
    # Cache the grading instructions
    hash = get_grading_instructions_hash(exercise_model)
    store_structured_grading_criterion(exercise_model.exercise_id, hash, grading_instruction_result)

    return grading_instruction_result

def get_grading_instructions_hash(exercise: ExerciseModel) -> str:

    hashable_data = {
        "problem_statement": exercise.problem_statement,
        "grading_instructions": exercise.grading_instructions,
        "sample_solution": exercise.transformed_example_solution,
        "max_points": exercise.max_points,
        "bonus_points": exercise.bonus_points,
    }

    json_string = json.dumps(hashable_data, sort_keys=True, default=str)
    return hashlib.sha256(json_string.encode()).hexdigest()

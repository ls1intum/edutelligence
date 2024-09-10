from typing import List, Optional
from athena.metadata import emit_meta
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate

from athena.schemas.grading_criterion import GradingCriterion, StructuredGradingCriterion
from module_modeling_llm.utils.predict_and_parse import predict_and_parse
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
            structured_instructions_output_format=PydanticOutputParser(pydantic_object=StructuredGradingCriterion).get_format_instructions()
        )

    grading_instruction_result = await predict_and_parse(
        model=config.model.get_model(),
        chat_prompt=chat_prompt,
        prompt_input=prompt_inputs.dict(),
        pydantic_object=StructuredGradingCriterion,
        tags=[
            f"exercise-{exercise_model.exerciseId}",
            f"submission-{exercise_model.submissionId}",
        ]
    )

    if debug:
        emit_meta("get_structured_grading_instructions", {
            "prompt": chat_prompt.format(**prompt_inputs.dict()),
            "result": grading_instruction_result.dict() if grading_instruction_result is not None else None
        })

    if not grading_instruction_result:
        raise ValueError("No structured grading instructions were returned by the model.")

    return grading_instruction_result
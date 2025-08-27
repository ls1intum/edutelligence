from athena.schemas.structured_grading_criterion import StructuredGradingCriterion
from langchain_core.prompts import ChatPromptTemplate

from athena import emit_meta
from module_modeling_llm.config import BasicApproachConfig
from module_modeling_llm.models.assessment_model import AssessmentModel
from module_modeling_llm.prompts.apollon_format_description import (
    apollon_format_description,
)
from llm_core.core.predict_and_parse import predict_and_parse
from module_modeling_llm.prompts.graded_feedback_prompt import GradedFeedbackInputs
from module_modeling_llm.models.exercise_model import ExerciseModel


async def generate_suggestions(
    exercise_model: ExerciseModel,
    structured_grading_instructions: StructuredGradingCriterion,
    config: BasicApproachConfig,
    debug: bool,
) -> AssessmentModel:
    """
    Generate feedback suggestions for modeling exercise submissions
    :param exercise: The exercise for which a submission is assessed
    :param submission: The submission that is assessed
    :param is_graded: Indicates whether the submission is graded
    :param config: A configuration object for the feedback module
    :param debug: Indicates whether additional debugging information should be provided
    :return: A list of feedback items for the assessed submission
    """

    prompt_inputs = GradedFeedbackInputs(
        submission=exercise_model.transformed_submission,
        problem_statement=exercise_model.problem_statement,
        max_points=exercise_model.max_points,
        bonus_points=exercise_model.bonus_points,
        structured_grading_instructions=structured_grading_instructions.model_dump_json(),
        submission_uml_type=exercise_model.submission_uml_type,
        example_solution=exercise_model.transformed_example_solution,
        uml_diagram_format=apollon_format_description,
    )

    chat_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                config.generate_suggestions_prompt.graded_feedback_system_message,
            ),
            ("human", config.generate_suggestions_prompt.graded_feedback_human_message),
        ]
    )

    feedback_result = await predict_and_parse(
        model=config.generate_feedback,
        chat_prompt=chat_prompt,
        prompt_input=prompt_inputs.model_dump(),
        pydantic_object=AssessmentModel,
        tags=[
            f"exercise-{exercise_model.exercise_id}",
            f"submission-{exercise_model.submission_id}",
        ],
    )

    if debug:
        emit_meta(
            "generate_suggestions",
            {
                "prompt": chat_prompt.format(**prompt_inputs.model_dump()),
                "result": (
                    feedback_result.model_dump() if feedback_result is not None else None
                ),
            },
        )

    if feedback_result is None:
        raise ValueError("No feedback was generated")

    return feedback_result

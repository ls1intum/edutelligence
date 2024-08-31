import json
from typing import List, Optional, Sequence

from module_modeling_llm.prompts.apollon_format import apollon_format_description
from pydantic import BaseModel, Field

from athena import emit_meta
from athena.logger import logger
from athena.modeling import Exercise, Submission, Feedback
from module_modeling_llm.config import BasicApproachConfig
from module_modeling_llm.helpers.llm_utils import (
    get_chat_prompt_with_formatting_instructions,
    predict_and_parse
)

from module_modeling_llm.helpers.serializers.diagram_model_serializer import DiagramModelSerializer
from module_modeling_llm.helpers.utils import format_grading_instructions


class FeedbackModel(BaseModel):
    title: str = Field(description="Very short title, i.e. feedback category or similar", example="Logic Error")
    description: str = Field(description="Feedback description")
    element_names: Optional[List[str]] = Field(description="Referenced diagram element names, and relations (R<number>) or empty if unreferenced")
    credits: float = Field(0.0, description="Number of points received/deducted")
    grading_instruction_id: Optional[int] = Field(
        description="ID of the grading instruction that was used to generate this feedback, or empty if no grading instruction was used"
    )

    class Config:
        title = "Feedback"


class AssessmentModel(BaseModel):
    """Collection of feedbacks making up an assessment"""

    feedbacks: Sequence[FeedbackModel] = Field(description="Assessment feedbacks, make sure to include all grading instructions")

    class Config:
        title = "Assessment"


async def generate_suggestions(exercise: Exercise, submission: Submission, config: BasicApproachConfig, debug: bool) -> \
        List[Feedback]:
    """
    Generate feedback suggestions for modeling exercise submissions
    :param exercise: The exercise for which a submission is assessed
    :param submission: The submission that is assessed
    :param config: A configuration object for the feedback module
    :param debug: Indicates whether additional debugging information should be provided
    :return: A list of feedback items for the assessed submission
    """
    model = config.model.get_model()  # type: ignore[attr-defined]

    print("Model ", model)

    serialized_example_solution = None
    if exercise.example_solution:
        example_solution_diagram = json.loads(exercise.example_solution)
        serialized_example_solution, _ = DiagramModelSerializer.serialize_model(example_solution_diagram)

    submission_diagram = json.loads(submission.model)
    serialized_submission, element_id_mapping = DiagramModelSerializer.serialize_model(submission_diagram)

    prompt_input = {
        "max_points": exercise.max_points,
        "bonus_points": exercise.bonus_points,
        "grading_instructions": format_grading_instructions(exercise.grading_instructions, exercise.grading_criteria),
        "submission_format": submission_diagram.get("type"),
        "problem_statement": exercise.problem_statement or "No problem statement.",
        "example_solution": serialized_example_solution or "No example solution.",
        "submission": serialized_submission,
        "uml_diagram_format": apollon_format_description
    }

    chat_prompt = get_chat_prompt_with_formatting_instructions(
        system_message=config.generate_suggestions_prompt.system_message,
        human_message=config.generate_suggestions_prompt.human_message,
        pydantic_object=AssessmentModel
    )

    result = await predict_and_parse(
        model=model,
        chat_prompt=chat_prompt,
        prompt_input=prompt_input,
        pydantic_object=AssessmentModel,
        tags=[
            f"exercise-{exercise.id}",
            f"submission-{submission.id}",
        ]
    )

    if debug:
        emit_meta("generate_suggestions", {
            "prompt": chat_prompt.format(**prompt_input),
            "result": result.dict() if result is not None else None
        })

    if result is None:
        return []

    grading_instruction_ids = set(
        grading_instruction.id
        for criterion in exercise.grading_criteria or []
        for grading_instruction in criterion.structured_grading_instructions
    )

    feedbacks = []
    for feedback in result.feedbacks:
        grading_instruction_id = feedback.grading_instruction_id if feedback.grading_instruction_id in grading_instruction_ids else None
        element_ids = [element_id_mapping[element] for element in (feedback.element_names or [])]


        feedbacks.append(Feedback(
            exercise_id=exercise.id,
            submission_id=submission.id,
            title=feedback.title,
            description=feedback.description,
            element_ids=element_ids,
            credits=feedback.credits,
            structured_grading_instruction_id=grading_instruction_id,
            meta={},
            id=None,
            is_graded=False
        ))

    return feedbacks
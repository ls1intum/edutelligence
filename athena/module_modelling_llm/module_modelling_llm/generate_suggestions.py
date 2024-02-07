import json
from typing import List, Optional, Sequence

from pydantic import BaseModel, Field

from athena import emit_meta
from athena.logger import logger
from athena.modelling import Exercise, Submission, Feedback
from module_modelling_llm.config import BasicApproachConfig
from module_modelling_llm.helpers.llm_utils import (
    get_chat_prompt_with_formatting_instructions,
    check_prompt_length_and_omit_features_if_necessary,
    num_tokens_from_prompt,
    predict_and_parse
)
from module_modelling_llm.helpers.models.diagram_types import DiagramType
from module_modelling_llm.helpers.serializers.diagram_model_serializer import DiagramModelSerializer
from module_modelling_llm.helpers.utils import format_grading_instructions
from module_modelling_llm.prompts.submission_format.submission_format_remarks import get_submission_format_remarks


class FeedbackModel(BaseModel):
    title: str = Field(description="Very short title, i.e. feedback category or similar", example="Logic Error")
    description: str = Field(description="Feedback description")
    element_ids: Optional[str] = Field(description="Referenced diagram element IDs, or empty if unreferenced")
    credits: float = Field(0.0, description="Number of points received/deducted")
    grading_instruction_id: Optional[int] = Field(
        description="ID of the grading instruction that was used to generate this feedback, or empty if no grading instruction was used"
    )

    class Config:
        title = "Feedback"


class AssessmentModel(BaseModel):
    """Collection of feedbacks making up an assessment"""

    feedbacks: Sequence[FeedbackModel] = Field(description="Assessment feedbacks")

    class Config:
        title = "Assessment"


async def generate_suggestions(exercise: Exercise, submission: Submission, config: BasicApproachConfig, debug: bool) -> \
        List[Feedback]:
    model = config.model.get_model()  # type: ignore[attr-defined]

    serialized_example_solution = None

    if exercise.example_solution:
        example_solution_diagram = json.loads(exercise.example_solution)
        serialized_example_solution, _ = DiagramModelSerializer.serialize_model(example_solution_diagram)

    submission_diagram = json.loads(submission.model)
    submission_format_remarks = get_submission_format_remarks(DiagramType[submission_diagram.get("type")])

    # Having the LLM reference IDs that a specific feedback item applies to seems to work a lot more reliable with
    # shorter IDs, especially if they are prefixed with "id_". We therefore map the UUIDs used in Apollon diagrams to
    # shortened IDs and have the diagram model serializer return a reverse mapping dictionary which allows us to map
    # the shortened IDs back to the original ones.
    serialized_submission, reverse_id_map = DiagramModelSerializer.serialize_model(submission_diagram)

    prompt_input = {
        "max_points": exercise.max_points,
        "bonus_points": exercise.bonus_points,
        "grading_instructions": format_grading_instructions(exercise.grading_instructions, exercise.grading_criteria),
        "submission_format_remarks": submission_format_remarks,
        "problem_statement": exercise.problem_statement or "No problem statement.",
        "example_solution": serialized_example_solution or "No example solution.",
        "submission": serialized_submission
    }

    chat_prompt = get_chat_prompt_with_formatting_instructions(
        model=model,
        system_message=config.generate_suggestions_prompt.system_message,
        human_message=config.generate_suggestions_prompt.human_message,
        pydantic_object=AssessmentModel
    )

    # Check if the prompt is too long and omit features if necessary (in order of importance)
    omittable_features = ["example_solution", "problem_statement", "grading_instructions"]
    prompt_input, should_run = check_prompt_length_and_omit_features_if_necessary(
        prompt=chat_prompt,
        prompt_input=prompt_input,
        max_input_tokens=10000,  # config.max_input_tokens,
        omittable_features=omittable_features,
        debug=debug
    )

    # Skip if the prompt is too long
    if not should_run:
        logger.warning("Input too long. Skipping.")
        if debug:
            emit_meta("prompt", chat_prompt.format(**prompt_input))
            emit_meta("error",
                      f"Input too long {num_tokens_from_prompt(chat_prompt, prompt_input)} > {config.max_input_tokens}")
        return []

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
        feedbacks.append(Feedback(
            exercise_id=exercise.id,
            submission_id=submission.id,
            title=feedback.title,
            description=feedback.description,
            element_ids=list(
                map(lambda element_id: reverse_id_map[
                    element_id.strip()
                ] if reverse_id_map else element_id.strip(), feedback.element_ids.split(","))
            ) if feedback.element_ids else [],
            credits=feedback.credits,
            structured_grading_instruction_id=grading_instruction_id,
            meta={}
        ))

    return feedbacks

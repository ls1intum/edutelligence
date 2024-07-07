from typing import List, Optional, Sequence
import os
import asyncio

from langchain_core.prompts import SystemMessagePromptTemplate, HumanMessagePromptTemplate, ChatPromptTemplate
from langchain_core.pydantic_v1 import BaseModel, Field

from athena import emit_meta
from athena.programming import Exercise, Submission, Feedback
from module_programming_llm.graded.zero_shot.config import GradedZeroShotConfig

from module_programming_llm.helpers.llm_utils import (
    check_prompt_length_and_omit_features_if_necessary,
    get_chat_prompt_with_formatting_instructions,
    num_tokens_from_string,
    predict_and_parse,
)
from module_programming_llm.helpers.utils import (
    get_diff,
    load_files_from_repo,
    add_line_numbers,
    get_programming_language_file_extension, format_grading_instructions,
)


class FeedbackModel(BaseModel):
    title: str = Field(
        description="Very short title, i.e. feedback category", example="Logic Error"
    )
    description: str = Field(description="Feedback description")
    line_start: Optional[int] = Field(
        description="Referenced line number start, or empty if unreferenced"
    )
    line_end: Optional[int] = Field(
        description="Referenced line number end, or empty if unreferenced"
    )
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


# pylint: disable=too-many-locals
async def generate_graded_zero_shot_suggestions(
    exercise: Exercise,
    submission: Submission,
    config: GradedZeroShotConfig,
    debug: bool,
) -> List[Feedback]:
    model = config.model.get_model()  # type: ignore[attr-defined]

    system_message_prompt = SystemMessagePromptTemplate.from_template(config.prompt.system_message)
    file_message_prompt = HumanMessagePromptTemplate.from_template(config.prompt.file_message)

    prompt_inputs: List[dict] = []

    # Feature extraction
    template_repo = exercise.get_template_repository()
    solution_repo = exercise.get_solution_repository()
    submission_repo = submission.get_repository()

    changed_files_from_template_to_submission = get_diff(
        src_repo=template_repo, dst_repo=submission_repo, file_path=None, name_only=True
    ).split("\n")
    changed_files_from_template_to_submission = [
        os.path.join(str(submission_repo.working_tree_dir or ""), file_path)
        for file_path in changed_files_from_template_to_submission
    ]

    # Changed text files
    loaded_changed_files = load_files_from_repo(
        submission_repo,
        file_filter=lambda file_path: file_path
                                      in changed_files_from_template_to_submission,
    )

    problem_statement = exercise.problem_statement or ""
    problem_statement = (
        problem_statement
        if problem_statement.strip()
        else "No problem statement found."
    )

    programming_language_extension = get_programming_language_file_extension(
        programming_language=exercise.programming_language
    )

    # Gather prompt inputs for each changed file (independently)
    for file_path, file_content in loaded_changed_files.items():
        if programming_language_extension and not file_path.endswith(programming_language_extension):
            continue

        file_content = add_line_numbers(file_content)
        solution_to_submission_diff = get_diff(
            src_repo=solution_repo,
            dst_repo=submission_repo,
            src_prefix="solution",
            dst_prefix="submission",
            file_path=file_path,
        )
        template_to_submission_diff = get_diff(
            src_repo=template_repo,
            dst_repo=submission_repo,
            src_prefix="template",
            dst_prefix="submission",
            file_path=file_path,
        )
        template_to_solution_diff = get_diff(
            src_repo=template_repo,
            dst_repo=solution_repo,
            src_prefix="template",
            dst_prefix="solution",
            file_path=file_path,
        )

        grading_instructions = format_grading_instructions(exercise.grading_instructions, exercise.grading_criteria)

        prompt_inputs.append(
            {
                "file_path": file_path,  # Not really relevant for the prompt, but necessary for e.g. logging purposes
                "submission_file": file_content,
                "solution_to_submission_diff": solution_to_submission_diff,
                "template_to_submission_diff": template_to_submission_diff,
                "priority": len(
                    template_to_solution_diff
                ),  # Not really relevant for the prompt, necessary for filtering
            }
        )

    prompt_input = {
        "max_points": exercise.max_points,
        "bonus_points": exercise.bonus_points,
        "grading_instructions": grading_instructions,
        "problem_statement": problem_statement,
        "prompt_inputs": prompt_inputs,
    }

    chat_prompt = ChatPromptTemplate.from_messages(
            [system_message_prompt]
            + [file_message_prompt.format(**prompt_input) for prompt_input in prompt_inputs]
        )

    # noinspection PyTypeChecker
    results: List[Optional[AssessmentModel]] = await predict_and_parse(
        model=model,
        chat_prompt=chat_prompt,
        prompt_input=prompt_input,
        pydantic_object=AssessmentModel,
        tags=[
            f"exercise-{exercise.id}",
            f"submission-{submission.id}",
            "one-shot-graded-suggestions",
        ],
    )

    if debug:
        emit_meta(
            "one-shot-graded-suggestions",
            [
                {
                    "file_path": prompt_input["file_path"],
                    "prompt": chat_prompt.format(**prompt_input),
                    "result": result.dict() if result is not None else None,
                }
                for prompt_input, result in zip(prompt_inputs, results)
            ],
        )

    grading_instruction_ids = set(
        grading_instruction.id
        for criterion in exercise.grading_criteria or []
        for grading_instruction in criterion.structured_grading_instructions
    )

    feedbacks: List[Feedback] = []
    for prompt_input, result in zip(prompt_inputs, results):
        file_path = prompt_input["file_path"]
        if result is None:
            continue
        for feedback in result.feedbacks:
            grading_instruction_id = (
                feedback.grading_instruction_id
                if feedback.grading_instruction_id in grading_instruction_ids
                else None
            )
            feedbacks.append(
                Feedback(
                    id=None,
                    exercise_id=exercise.id,
                    submission_id=submission.id,
                    title=feedback.title,
                    description=feedback.description,
                    file_path=file_path,
                    line_start=feedback.line_start,
                    line_end=feedback.line_end,
                    credits=feedback.credits,
                    structured_grading_instruction_id=grading_instruction_id,
                    is_graded=True,
                    meta={},
                )
            )

    return feedbacks
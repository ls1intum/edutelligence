from typing import List, Optional, Sequence
import asyncio
from pydantic import ConfigDict, BaseModel, Field

from athena import emit_meta
from athena.programming import Exercise, Submission, Feedback

from module_programming_quality_llm.config import GradedBasicApproachConfig
from llm_core.utils.llm_utils import (
    check_prompt_length_and_omit_features_if_necessary,
    get_chat_prompt,
)
from llm_core.core.predict_and_parse import predict_and_parse

from module_programming_quality_llm.helpers.utils import (
    load_files_from_repo,
    add_line_numbers,
    get_programming_language_file_extension,
)


class FeedbackModel(BaseModel):
    title: str = Field(
        description="Very short title, i.e. feedback category", examples=["Logic Error"]
    )
    description: str = Field(description="Feedback description")
    line_start: Optional[int] = Field(
        None, description="Referenced line number start, or empty if unreferenced"
    )
    line_end: Optional[int] = Field(
        None, description="Referenced line number end, or empty if unreferenced"
    )
    credits: float = Field(0.0, description="Number of points received/deducted")
    grading_instruction_id: Optional[int] = Field(
        None, description="ID of the grading instruction that was used to generate this feedback, or empty if no grading instruction was used"
    )
    model_config = ConfigDict(title="Feedback")


class AssessmentModel(BaseModel):
    """Collection of feedbacks making up an assessment"""

    feedbacks: Sequence[FeedbackModel] = Field(description="Assessment feedbacks")
    model_config = ConfigDict(title="Assessment")


# pylint: disable=too-many-locals
async def generate_suggestions_by_file(
    exercise: Exercise,
    submission: Submission,
    config: GradedBasicApproachConfig,
    debug: bool,
) -> List[Feedback]:

    chat_prompt = get_chat_prompt(
        system_message=config.generate_suggestions_by_file_prompt.system_message,
        human_message=config.generate_suggestions_by_file_prompt.human_message,
    )

    submission_repo = submission.get_repository()
    programming_language_extension = get_programming_language_file_extension(
        programming_language=exercise.programming_language
    )

    # Load project files, favoring language-specific source files
    project_files = load_files_from_repo(
        submission_repo,
        file_filter=(
            (lambda file_path: programming_language_extension is None or file_path.endswith(programming_language_extension))
        ),
    )

    # Fallback: if no files matched the extension, analyze all files
    if not project_files:
        project_files = load_files_from_repo(submission_repo)

    prompt_inputs: List[dict] = []

    for file_path, file_content in project_files.items():
        file_content_numbered = add_line_numbers(file_content)
        prompt_inputs.append(
            {
                "file_path": file_path,
                "submission_file": file_content_numbered,
                "priority": len(file_content_numbered),
            }
        )

    # Limit number of files; prioritize by size (as a proxy for importance)
    prompt_inputs = sorted(prompt_inputs, key=lambda x: x["priority"], reverse=True)
    prompt_inputs = prompt_inputs[: config.max_number_of_files]

    # Keep only fields used by the prompt
    for prompt_input in prompt_inputs:
        prompt_input.pop("priority", None)

    omittable_features: List[str] = []

    prompt_inputs = [
        omitted_prompt_input
        for omitted_prompt_input, should_run in [
            check_prompt_length_and_omit_features_if_necessary(
                prompt=chat_prompt,
                prompt_input=prompt_input,
                max_input_tokens=config.max_input_tokens,
                omittable_features=omittable_features,
                debug=debug,
            )
            for prompt_input in prompt_inputs
        ]
        if should_run
    ]

    # noinspection PyTypeChecker
    results: List[Optional[AssessmentModel]] = await asyncio.gather(
        *[
            predict_and_parse(
                model=config.model,
                chat_prompt=chat_prompt,
                prompt_input=prompt_input,
                pydantic_object=AssessmentModel,
                tags=[
                    f"exercise-{exercise.id}",
                    f"submission-{submission.id}",
                    f"file-{prompt_input['file_path']}",
                    "generate-suggestions-by-file",
                ],
            )
            for prompt_input in prompt_inputs
        ]
    )

    if debug:
        emit_meta(
            "generate_suggestions",
            [
                {
                    "file_path": prompt_input["file_path"],
                    "prompt": chat_prompt.format(**prompt_input),
                    "result": result.model_dump() if result is not None else None,
                }
                for prompt_input, result in zip(prompt_inputs, results)
            ],
        )

    feedbacks: List[Feedback] = []
    for prompt_input, result in zip(prompt_inputs, results):
        file_path = prompt_input["file_path"]
        if result is None:
            continue
        for feedback in result.feedbacks:
            feedbacks.append(
                Feedback(
                    exercise_id=exercise.id,
                    submission_id=submission.id,
                    title=feedback.title,
                    description=feedback.description,
                    file_path=file_path,
                    line_start=feedback.line_start,
                    line_end=feedback.line_end,
                    credits=feedback.credits,
                    structured_grading_instruction_id=None,
                    is_graded=True,
                    meta={},
                )
            )

    return feedbacks

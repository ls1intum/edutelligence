from typing import List, Optional, Sequence
import os
import asyncio
from pydantic import ConfigDict, BaseModel, Field

from athena import emit_meta
from athena.programming import Exercise, Submission, Feedback

from module_programming_llm.config import GradedBasicApproachConfig
from module_programming_llm.split_grading_instructions_by_file import (
    split_grading_instructions_by_file,
)
from module_programming_llm.split_problem_statement_by_file import (
    split_problem_statement_by_file,
)
from llm_core.utils.llm_utils import (
    check_prompt_length_and_omit_features_if_necessary,
    get_chat_prompt,
    num_tokens_from_string,
)
from llm_core.core.predict_and_parse import predict_and_parse

from module_programming_llm.helpers.utils import (
    get_diff,
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

    # Get split problem statement and grading instructions by file (if necessary)
    split_problem_statement, split_grading_instructions = await asyncio.gather(
        split_problem_statement_by_file(
            exercise=exercise,
            submission=submission,
            prompt=chat_prompt,
            config=config,
            debug=debug,
        ),
        split_grading_instructions_by_file(
            exercise=exercise,
            submission=submission,
            prompt=chat_prompt,
            config=config,
            debug=debug,
        ),
    )

    problem_statement_tokens = num_tokens_from_string(exercise.problem_statement or "")
    is_short_problem_statement = (
        problem_statement_tokens
        <= config.split_problem_statement_by_file_prompt.tokens_before_split
    )
    file_problem_statements = (
        {
            item.file_name: item.problem_statement
            for item in split_problem_statement.items
        }
        if split_problem_statement is not None
        else {}
    )

    is_short_grading_instructions = (
        num_tokens_from_string(exercise.grading_instructions)
        <= config.split_grading_instructions_by_file_prompt.tokens_before_split
        if exercise.grading_instructions is not None
        else True
    )
    file_grading_instructions = (
        {
            item.file_name: item.grading_instructions
            for item in split_grading_instructions.items
        }
        if split_grading_instructions is not None
        else {}
    )

    prompt_inputs: List[dict] = []

    # Feature extraction
    solution_repo = exercise.get_solution_repository()
    template_repo = exercise.get_template_repository()
    submission_repo = submission.get_repository()

    changed_files_from_template_to_submission = get_diff(
        src_repo=template_repo, dst_repo=submission_repo, file_path=None, name_only=True
    ).split("\n")
    changed_files_from_template_to_submission = [
        os.path.join(str(submission_repo.working_tree_dir or ""), file_path)
        for file_path in changed_files_from_template_to_submission
    ]

    # Changed text files
    changed_files = load_files_from_repo(
        submission_repo,
        file_filter=lambda file_path: file_path
        in changed_files_from_template_to_submission,
    )

    # Gather prompt inputs for each changed file (independently)
    for file_path, file_content in changed_files.items():
        problem_statement = (
            exercise.problem_statement or ""
            if is_short_problem_statement
            else file_problem_statements.get(
                file_path, "No relevant problem statement section found."
            )
        )
        problem_statement = (
            problem_statement
            if problem_statement.strip()
            else "No problem statement found."
        )

        grading_instructions = (
            exercise.grading_instructions or ""
            if is_short_grading_instructions
            else file_grading_instructions.get(
                file_path, "No relevant grading instructions found."
            )
        )
        grading_instructions = (
            grading_instructions
            if grading_instructions.strip()
            else "No grading instructions found."
        )

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

        prompt_inputs.append(
            {
                "file_path": file_path,  # Not really relevant for the prompt
                "priority": len(
                    template_to_solution_diff
                ),  # Not really relevant for the prompt
                "submission_file": file_content,
                "max_points": exercise.max_points,
                "bonus_points": exercise.bonus_points,
                "solution_to_submission_diff": solution_to_submission_diff,
                "template_to_submission_diff": template_to_submission_diff,
                "template_to_solution_diff": template_to_solution_diff,
                "grading_instructions": grading_instructions,
                "problem_statement": problem_statement,
            }
        )

    # Filter long prompts (omitting features if necessary)
    # Lowest priority features are at the top of the list (i.e. they are omitted first if necessary)
    # "submission_file" is not omittable, because it is the main input containing the line numbers
    # In the future we might be able to include the line numbers in the diff, but for now we need to keep it
    omittable_features = [
        "template_to_solution_diff",  # If it is even included in the prompt (has the lowest priority since it is indirectly included in other diffs)
        "problem_statement",
        "grading_instructions",
        "solution_to_submission_diff",
        "template_to_submission_diff",  # In the future we might indicate the changed lines in the submission_file additionally
    ]

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

    # If we have many files we need to filter and prioritize them
    if len(prompt_inputs) > config.max_number_of_files:
        programming_language_extension = get_programming_language_file_extension(
            programming_language=exercise.programming_language
        )

        # Prioritize files that have a diff between solution and submission
        prompt_inputs = sorted(prompt_inputs, key=lambda x: x["priority"], reverse=True)

        filtered_prompt_inputs = []
        if programming_language_extension is not None:
            filtered_prompt_inputs = [
                prompt_input
                for prompt_input in prompt_inputs
                if prompt_input["file_path"].endswith(programming_language_extension)
            ]

        while (
            len(filtered_prompt_inputs) < config.max_number_of_files and prompt_inputs
        ):
            filtered_prompt_inputs.append(prompt_inputs.pop(0))
        prompt_inputs = filtered_prompt_inputs

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

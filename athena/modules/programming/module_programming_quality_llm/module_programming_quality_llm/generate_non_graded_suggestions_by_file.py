from typing import List, Optional, Sequence
import os
import asyncio
from pydantic import ConfigDict, BaseModel, Field

from athena import emit_meta
from athena.programming import Exercise, Submission, Feedback

from module_programming_quality_llm.config import NonGradedBasicApproachConfig
from module_programming_quality_llm.generate_summary_by_file import generate_summary_by_file
from module_programming_quality_llm.split_problem_statement_by_file import (
    split_problem_statement_by_file,
)
from llm_core.utils.llm_utils import (
    check_prompt_length_and_omit_features_if_necessary,
    get_chat_prompt,
    num_tokens_from_string,
)
from llm_core.core.predict_and_parse import predict_and_parse

from module_programming_quality_llm.helpers.utils import (
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
    model_config = ConfigDict(title="Feedback")


class ImprovementModel(BaseModel):
    """Collection of feedbacks making up an improvement"""

    feedbacks: Sequence[FeedbackModel] = Field(description="Improvement feedbacks")
    model_config = ConfigDict(title="ImprovementModel")


# pylint: disable=too-many-locals
async def generate_suggestions_by_file(
    exercise: Exercise,
    submission: Submission,
    config: NonGradedBasicApproachConfig,
    debug: bool,
) -> List[Feedback]:

    chat_prompt = get_chat_prompt(
        system_message=config.generate_suggestions_by_file_prompt.system_message,
        human_message=config.generate_suggestions_by_file_prompt.human_message,
    )

    prompt_inputs: List[dict] = []

    # Feature extraction
    template_repo = exercise.get_template_repository()
    submission_repo = submission.get_repository()

    changed_files_from_template_to_submission = get_diff(
        src_repo=template_repo, dst_repo=submission_repo, file_path=None, name_only=True
    ).split("\n")
    changed_files_from_template_to_submission = [
        os.path.join(str(submission_repo.working_tree_dir or ""), file_path)
        for file_path in changed_files_from_template_to_submission
    ]

    # Changed files but filtered for programming language
    programming_language_extension = get_programming_language_file_extension(
        programming_language=exercise.programming_language
    )

    changed_files = load_files_from_repo(
        submission_repo,
        file_filter=lambda file_path: (
                file_path in changed_files_from_template_to_submission
                and (programming_language_extension is None
                     or file_path.endswith(programming_language_extension))
        ),
    )

    # Get solution summary by file (if necessary)
    solution_summary = await generate_summary_by_file(
        exercise=exercise,
        submission=submission,
        prompt=chat_prompt,
        config=config,
        debug=debug,
    )
    summary_string = solution_summary.describe_solution_summary() if solution_summary is not None else ""


    # Get split problem statement by file (if necessary)
    split_problem_statement = await split_problem_statement_by_file(
        exercise=exercise,
        submission=submission,
        prompt=chat_prompt,
        config=config,
        debug=debug,
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

        file_content = add_line_numbers(file_content)
        diff_lines = get_diff(
            src_repo=template_repo,
            dst_repo=submission_repo,
            src_prefix="template",
            dst_prefix="submission",
            file_path=file_path,
        )

        diff_lines_list = diff_lines.split("\n")

        diff_without_deletions = []

        for line in diff_lines_list:
            if not line.startswith("-"):
                diff_without_deletions.append(line)

        template_to_submission_diff = "\n".join(diff_without_deletions)

        added_lines = sum(
            1 for line in diff_lines_list
            if line.startswith("+") and not line.startswith("+++")
        )

        prompt_inputs.append(
            {
                "submission_file": file_content,
                "template_to_submission_diff": template_to_submission_diff,
                "problem_statement": problem_statement,
                "file_path": file_path,
                "summary": summary_string,
                "priority": added_lines,
            }
        )

    omittable_features = [
        "summary",
        "problem_statement",
        # In the future we might indicate the changed lines in the submission_file additionally
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

        # Prioritize files that have a diff between solution and submission
        prompt_inputs = sorted(prompt_inputs, key=lambda x: x.get("priority", 0), reverse=True)

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
    BATCH_SIZE = 15  # Process files in batches

    async def process_in_batches(
            prompt_inputs: List[dict],
            model,
            chat_prompt,
            exercise,
            submission,
    ) -> List[Optional[ImprovementModel]]:
        results = []
        for i in range(0, len(prompt_inputs), BATCH_SIZE):
            batch = prompt_inputs[i:i + BATCH_SIZE]
            batch_results = await asyncio.gather(
                *[
                    predict_and_parse(
                        model=model,
                        chat_prompt=chat_prompt,
                        prompt_input=prompt_input,
                        pydantic_object=ImprovementModel,
                        tags=[
                            f"exercise-{exercise.id}",
                            f"submission-{submission.id}",
                            f"file-{prompt_input['file_path']}",
                            "generate-suggestions-by-file",
                        ],
                    )
                    for prompt_input in batch
                ]
            )
            results.extend(batch_results)
        return results

    # noinspection PyTypeChecker
    results: List[Optional[ImprovementModel]] = await process_in_batches(
        prompt_inputs=prompt_inputs,
        model=config.model,
        chat_prompt=chat_prompt,
        exercise=exercise,
        submission=submission,
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
                    is_graded=False,
                    meta={},
                )
            )

    return feedbacks

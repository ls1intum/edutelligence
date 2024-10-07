import asyncio
import os
from typing import Optional, List

from athena import emit_meta
from module_programming_llm.prompts.pipeline_step import PipelineStep
from .generate_suggestions_by_file_input import GenerateSuggestionsByFileInput
from .generate_suggestions_by_file_output import GenerateSuggestionsByFileOutput, FeedbackModel
from .prompt import system_message as prompt_system_message, human_message as prompt_human_message
from pydantic import Field
from module_programming_llm.helpers.llm_utils import (
    get_chat_prompt_with_formatting_instructions,
    predict_and_parse, num_tokens_from_string,
    check_prompt_length_and_omit_features_if_necessary,
)
from module_programming_llm.helpers.utils import (
    get_diff,
    load_files_from_repo,
    add_line_numbers, get_programming_language_file_extension
)
from ...helpers.models import ModelConfigType


class GenerateSuggestionsByFile(PipelineStep[GenerateSuggestionsByFileInput, List[Optional[GenerateSuggestionsByFileOutput]]]):
    """Generates concise feedback for submitted files, facilitating a quicker review and understanding of the content"""

    system_message: str = Field(prompt_system_message,
                                description="Message for priming AI behavior and instructing it what to do.")
    human_message: str = Field(prompt_human_message,
                               description="Message from a human. The input on which the AI is supposed to act.")
    max_number_of_files: int = Field(default=25,
                                     description="Maximum number of files. If exceeded, it will prioritize the most important ones.")
    tokens_before_split: int = Field(default=250,
                                     description="Split the grading instructions into file-based ones after this number of tokens.")

    # pylint: disable=too-many-locals
    async def process(self, input_data: GenerateSuggestionsByFileInput, debug: bool, model: ModelConfigType) -> List[Optional[GenerateSuggestionsByFileOutput]]: # type: ignore
        model = model.get_model() # type: ignore[attr-defined]

        prompt = get_chat_prompt_with_formatting_instructions(
            model=model,
            system_message=self.system_message,
            human_message=self.human_message,
            pydantic_object=GenerateSuggestionsByFileOutput,
        )

        problem_statement_tokens = num_tokens_from_string(input_data.problem_statement or "")
        is_short_problem_statement = (
                problem_statement_tokens
                <= self.tokens_before_split
        )
        file_problem_statements = (
            {
                item.file_path: item.problem_statement
                for item in input_data.problem_statement_by_file.items
            }
            if input_data.problem_statement_by_file is not None
            else {}
        )

        is_short_grading_instructions = (
            num_tokens_from_string(input_data.grading_instructions)
            <= self.tokens_before_split
            if input_data.grading_instructions is not None
            else True
        )
        file_grading_instructions = (
            {
                item.file_path: item.grading_instructions
                for item in input_data.grading_instructions_by_file.items
            }
            if input_data.grading_instructions_by_file is not None
            else {}
        )

        prompt_inputs: List[dict] = []

        solution_repo = input_data.solution_repo
        template_repo = input_data.template_repo
        submission_repo = input_data.submission_repo

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
            file_filter=lambda file_path: file_path in changed_files_from_template_to_submission,
        )

        # Gather prompt inputs for each changed file (independently)
        for file_path, file_content in changed_files.items():
            problem_statement = (
                input_data.problem_statement or ""
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
                input_data.grading_instructions or ""
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
                    "max_points": input_data.max_points,
                    "bonus_points": input_data.bonus_points,
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
            "template_to_solution_diff",
            # If it is even included in the prompt (has the lowest priority since it is indirectly included in other diffs)
            "problem_statement",
            "grading_instructions",
            "solution_to_submission_diff",
            "template_to_submission_diff",
            # In the future we might indicate the changed lines in the submission_file additionally
        ]

        prompt_inputs = [
            omitted_prompt_input
            for omitted_prompt_input, should_run in [
                check_prompt_length_and_omit_features_if_necessary(
                    prompt=prompt,
                    prompt_input=prompt_input,
                    max_input_tokens=self.max_input_tokens,
                    omittable_features=omittable_features,
                    debug=debug,
                )
                for prompt_input in prompt_inputs
            ]
            if should_run
        ]

        # If we have many files we need to filter and prioritize them
        if len(prompt_inputs) > self.max_number_of_files:
            programming_language_extension = get_programming_language_file_extension(
                programming_language=input_data.programming_language
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
                    len(filtered_prompt_inputs) < self.max_number_of_files and prompt_inputs
            ):
                filtered_prompt_inputs.append(prompt_inputs.pop(0))
            prompt_inputs = filtered_prompt_inputs

        # noinspection PyTypeChecker
        results: List[Optional[GenerateSuggestionsByFileOutput]] = await asyncio.gather(
            *[
                predict_and_parse(
                    model=model,
                    chat_prompt=prompt,
                    prompt_input=prompt_input,
                    pydantic_object=GenerateSuggestionsByFileOutput,
                    tags=[
                        f"exercise-{input_data.exercise_id}",
                        f"submission-{input_data.submission_id}",
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
                        "prompt": prompt.format(**prompt_input),
                        "result": result.dict() if result is not None else None,
                    }
                    for prompt_input, result in zip(prompt_inputs, results)
                ],
            )

        return results
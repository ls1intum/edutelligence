import asyncio
import json
import os
from collections import defaultdict
from typing import Optional, List, Sequence, Dict

from athena import emit_meta
from module_programming_llm.prompts.pipeline_step import PipelineStep
from .filter_out_solution_input import FilterOutSolutionInput
from .filter_out_solution_output import FilterOutSolutionOutput, FeedbackModel as FilterOutFeedbackModel
from module_programming_llm.prompts.generate_suggestions_by_file.generate_suggestions_by_file_output import FeedbackModel as SuggestionsFeedbackModel
from .prompt import system_message, human_message
from pydantic import Field
from module_programming_llm.helpers.llm_utils import (
    get_chat_prompt_with_formatting_instructions,
    predict_and_parse, num_tokens_from_string,
    check_prompt_length_and_omit_features_if_necessary,
)
from module_programming_llm.helpers.utils import (
    get_diff,
    load_files_from_repo,
    add_line_numbers
)
from ...helpers.models import ModelConfigType


class FilterOutSolution(PipelineStep[FilterOutSolutionInput, List[Optional[FilterOutSolutionOutput]]]):
    """Generates concise summaries of submission files, facilitating a quicker review and understanding of the content for AI processing."""

    system_message: str = Field(system_message,
                                description="Message for priming AI behavior and instructing it what to do.")
    human_message: str = Field(human_message,
                               description="Message from a human. The input on which the AI is supposed to act.")
    tokens_before_split: int = Field(default=250,
                                     description="Split the grading instructions into file-based ones after this number of tokens.")

    # pylint: disable=too-many-locals
    async def process(
            self,
            input_data: FilterOutSolutionInput,
            debug: bool,
            model: ModelConfigType
    ) -> List[Optional[FilterOutSolutionOutput]]:
        model = model.get_model()  # type: ignore[attr-defined]

        # Prepare the prompt template
        prompt = get_chat_prompt_with_formatting_instructions(
            model=model,
            system_message=self.system_message,
            human_message=self.human_message,
            pydantic_object=FilterOutSolutionOutput,
        )

        problem_statement_tokens = num_tokens_from_string(input_data.problem_statement or "")
        is_short_problem_statement = problem_statement_tokens <= self.tokens_before_split
        file_problem_statements = (
            {
                item.file_path: item.problem_statement
                for item in input_data.problem_statement_by_file.items
            }
            if input_data.problem_statement_by_file is not None
            else {}
        )

        prompt_inputs: List[dict] = []

        solution_repo = input_data.solution_repo
        template_repo = input_data.template_repo

        changed_files_from_template_to_solution = get_diff(
            src_repo=template_repo, dst_repo=solution_repo, file_path=None, name_only=True
        ).split("\n")
        changed_files_from_template_to_solution = [
            os.path.join(str(solution_repo.working_tree_dir or ""), file_path)
            for file_path in changed_files_from_template_to_solution
        ]

        # Changed text files
        changed_files = load_files_from_repo(
            solution_repo,
            file_filter=lambda file_path: file_path
                                          in changed_files_from_template_to_solution,
        )

        feedback_suggestions_by_file: Dict[str, Sequence[SuggestionsFeedbackModel]] = {}
        for feedback in input_data.feedback_suggestions:
            feedback_suggestions_by_file[feedback.file_path] = feedback.feedbacks

        # Gather prompt inputs for each file
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

            template_to_solution_diff = get_diff(
                src_repo=template_repo,
                dst_repo=solution_repo,
                src_prefix="template",
                dst_prefix="solution",
                file_path=file_path,
            )

            file_content = add_line_numbers(file_content)

            prompt_inputs.append(
                {
                    "file_path": file_path,
                    "code_with_line_numbers": file_content,
                    "problem_statement": problem_statement,
                    "template_to_solution_diff": template_to_solution_diff,
                    "feedback_suggestions": json.dumps([ob.__dict__ for ob in feedback_suggestions_by_file.get(file_path) or []])
                }
            )

        # Filter long prompts if necessary
        omittable_features = [
            "problem_statement",
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

        # Send prompts to the LLM
        # noinspection PyTypeChecker
        results: List[Optional[FilterOutSolutionOutput]] = await asyncio.gather(
            *[
                predict_and_parse(
                    model=model,
                    chat_prompt=prompt,
                    prompt_input=prompt_input,
                    pydantic_object=FilterOutSolutionOutput,
                    tags=[
                        f"exercise-{input_data.exercise_id}",
                        f"submission-{input_data.submission_id}",
                        f"file-{prompt_input['file_path']}",
                        "filter-out-solution",
                    ],
                )
                for prompt_input in prompt_inputs
            ]
        )

        if debug:
            emit_meta(
                "filter_out_solutions",
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
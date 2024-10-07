import asyncio
import os
from typing import Optional, List

from athena import emit_meta
from .generate_file_summary_input import GenerateFileSummaryInput
from .generate_file_summary_output import GenerateFileSummaryOutput
from module_programming_llm.prompts.pipeline_step import PipelineStep
from .generate_file_summary_output import FileDescription
from .prompt import system_message as prompt_system_message, human_message as prompt_human_message
from pydantic import Field
from module_programming_llm.helpers.llm_utils import (
    get_chat_prompt_with_formatting_instructions,
    predict_and_parse, num_tokens_from_prompt,
)
from module_programming_llm.helpers.utils import (
    get_diff,
    load_files_from_repo,
    add_line_numbers
)
from ...helpers.models import ModelConfigType


class GenerateFileSummary(PipelineStep[GenerateFileSummaryInput, Optional[GenerateFileSummaryOutput]]):
    """Generates concise summaries of submission files, facilitating a quicker review and understanding of the content for AI processing."""

    system_message: str = Field(prompt_system_message,
                                       description="Message for priming AI behavior and instructing it what to do.")
    human_message: str = Field(prompt_human_message,
                                      description="Message from a human. The input on which the AI is supposed to act.")

    # pylint: disable=too-many-locals
    async def process(self, input_data: GenerateFileSummaryInput, debug: bool, model: ModelConfigType) -> Optional[GenerateFileSummaryOutput]: # type: ignore
        """Generate a summary for the submission, file by file.

        Args:
            input_data (GenerateFileSummaryInput): Input data containing template and submission repositories.

        Returns:
            GenerateFileSummaryOutput: Summarized details of the submission files.
        """

        prompt = get_chat_prompt_with_formatting_instructions(
            model=model.get_model(),  # type: ignore[attr-defined]
            system_message=self.system_message,
            human_message=self.human_message,
            pydantic_object=FileDescription,
        )

        changed_files_from_template_to_submission = get_diff(
            src_repo=input_data.template_repo, dst_repo=input_data.submission_repo, file_path=None, name_only=True
        ).split("\n")

        changed_files_from_template_to_submission = [
            os.path.join(str(input_data.submission_repo.working_tree_dir or ""), file_path)
            for file_path in changed_files_from_template_to_submission
        ]

        # Changed text files
        changed_files = load_files_from_repo(
            input_data.submission_repo,
            file_filter=lambda file_path: file_path in changed_files_from_template_to_submission,
        )

        prompt_inputs = []

        # Gather prompt inputs for each file (independently)
        for file_path, file_content in changed_files.items():
            file_content = add_line_numbers(file_content)

            prompt_inputs.append(
                {
                    "submission_file": file_content,
                    "file_path": file_path,
                }
            )

        valid_prompt_inputs = [
            prompt_input
            for prompt_input in prompt_inputs
            if num_tokens_from_prompt(prompt, prompt_input) <= self.max_input_tokens
        ]

        # noinspection PyTypeChecker
        results: List[Optional[FileDescription]] = await asyncio.gather(
            *[
                predict_and_parse(
                    model=model.get_model(),  # type: ignore[attr-defined]
                    chat_prompt=prompt,
                    prompt_input=prompt_input,
                    pydantic_object=FileDescription,
                    tags=[
                        f"exercise-{input_data.exercise_id}",
                        f"submission-{input_data.submission_id}",
                        f"file-{prompt_input['file_path']}",
                        "generate-summary-by-file",
                    ],
                )
                for prompt_input in valid_prompt_inputs
            ]
        )

        if debug:
            for prompt_input, result in zip(valid_prompt_inputs, results):
                emit_meta(
                    "file_summary",
                    {
                        "prompt": prompt.format(**prompt_input),
                        "result": result.dict() if result is not None else None,
                        "file_path": prompt_input[
                            "file_path"
                        ],  # Include the file path for reference
                    },
                )

        if not any(result is not None for result in results):
            return None

        items_dict = {}

        for _, file_summary in enumerate(results):
            if file_summary is not None:
                items_dict[file_summary.file_path] = file_summary.description

        return GenerateFileSummaryOutput(items=items_dict)

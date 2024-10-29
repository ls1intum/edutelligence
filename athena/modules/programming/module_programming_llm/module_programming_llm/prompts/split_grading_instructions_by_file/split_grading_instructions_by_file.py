from collections import defaultdict

from module_programming_llm.helpers.utils import format_grading_instructions

from typing import Optional

from athena import emit_meta
from module_programming_llm.prompts.pipeline_step import PipelineStep
from .split_grading_instructions_by_file_input import SplitGradingInstructionsByFileInput
from .prompt import system_message as prompt_system_message, human_message as prompt_human_message
from pydantic import Field
from llm_core.utils.llm_utils import (
    get_chat_prompt_with_formatting_instructions,
    num_tokens_from_string,
    num_tokens_from_prompt,
)
from llm_core.utils.predict_and_parse import predict_and_parse
from module_programming_llm.helpers.utils import (
    get_diff,
)
from .split_grading_instructions_by_file_output import FileGradingInstruction, SplitGradingInstructionsByFileOutput
from llm_core.models import ModelConfigType


class SplitGradingInstructionsByFile(
    PipelineStep[SplitGradingInstructionsByFileInput, Optional[SplitGradingInstructionsByFileOutput]]):
    """Splits grading instructions of a programming exercise to match with solution files"""

    system_message: str = Field(prompt_system_message,
                                description="Message for priming AI behavior and instructing it what to do.")
    human_message: str = Field(prompt_human_message,
                               description="Message from a human. The input on which the AI is supposed to act.")
    tokens_before_split: int = Field(default=2000,
                                     description="Split the grading instructions into file-based ones after this number of tokens.")

    async def process(self, input_data: SplitGradingInstructionsByFileInput, debug: bool, model: ModelConfigType) -> Optional[SplitGradingInstructionsByFileOutput]: # type: ignore
        """Split the general grading instructions by file

        Args:
            input_data (SplitGradingInstructionsByFileInput): Input data containing template and submission repositories.

        Returns:
                Optional[SplitGradingInstructionsByFileOutput]: Split grading instructions, None if it is too short or too long
        """

        grading_instructions = format_grading_instructions(input_data.grading_instructions, input_data.grading_criteria)

        # Return None if the grading instructions are too short
        if (grading_instructions is None
                or num_tokens_from_string(
                    grading_instructions) <= self.tokens_before_split):
            return None

        changed_files_from_template_to_solution = get_diff(
            src_repo=input_data.template_repo, dst_repo=input_data.solution_repo, file_path=None, name_only=True
        ).split("\n")

        changed_files_from_template_to_submission = get_diff(
            src_repo=input_data.template_repo, dst_repo=input_data.submission_repo, file_path=None, name_only=True
        ).split("\n")

        prompt = get_chat_prompt_with_formatting_instructions(
            model=model.get_model(),  # type: ignore[attr-defined]
            system_message=self.system_message,
            human_message=self.human_message,
            pydantic_object=SplitGradingInstructionsByFileOutput,
        )

        prompt_input = {
            "grading_instructions": grading_instructions,
            "changed_files_from_template_to_solution": ", ".join(
                changed_files_from_template_to_solution
            ),
            "changed_files_from_template_to_submission": ", ".join(
                changed_files_from_template_to_submission
            ),
        }

        # Return None if the prompt is too long
        if num_tokens_from_prompt(prompt, prompt_input) > self.max_input_tokens:
            return None

        split_grading_instructions = await predict_and_parse(
            model=model.get_model(),  # type: ignore[attr-defined]
            chat_prompt=prompt,
            prompt_input=prompt_input,
            pydantic_object=SplitGradingInstructionsByFileOutput,
            tags=[
                f"exercise-{input_data.exercise_id}",
                f"submission-{input_data.submission_id}",
                "split-grading-instructions-by-file",
            ],
        )

        if debug:
            emit_meta(
                "file_grading_instructions",
                {
                    "prompt": prompt.format(**prompt_input),
                    "result": split_grading_instructions.dict()
                    if split_grading_instructions is not None
                    else None,
                },
            )

        if split_grading_instructions is None or not split_grading_instructions.items:
            return None

        # Join duplicate file names (some responses contain multiple grading instructions for the same file)
        file_grading_instructions_by_file_name = defaultdict(list)
        for file_grading_instruction in split_grading_instructions.items:
            file_grading_instructions_by_file_name[
                file_grading_instruction.file_name
            ].append(file_grading_instruction)

        split_grading_instructions.items = [
            FileGradingInstruction(
                file_name=file_name,
                grading_instructions="\n".join(
                    file_grading_instruction.grading_instructions
                    for file_grading_instruction in file_grading_instructions
                ),
            )
            for file_name, file_grading_instructions in file_grading_instructions_by_file_name.items()
        ]

        return split_grading_instructions

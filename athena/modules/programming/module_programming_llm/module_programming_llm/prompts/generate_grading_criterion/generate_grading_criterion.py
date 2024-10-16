import asyncio
import json
import os
from typing import Optional, List

from athena import emit_meta
from module_programming_llm.prompts.pipeline_step import PipelineStep
from .generate_grading_criterion_input import GenerateGradingCriterionInput
from .generate_grading_criterion_output import GenerateGradingCriterionOutput
from .prompt import system_message as prompt_system_message, human_message as prompt_human_message
from pydantic import Field
from module_programming_llm.helpers.llm_utils import (
    get_chat_prompt_with_formatting_instructions,
    predict_and_parse, num_tokens_from_string,
    check_prompt_length_and_omit_features_if_necessary, num_tokens_from_prompt,
)
from module_programming_llm.helpers.utils import (
    get_diff,
    load_files_from_repo,
    add_line_numbers, get_programming_language_file_extension
)
from ...helpers.models import ModelConfigType


class GenerateGradingCriterion(PipelineStep[GenerateGradingCriterionInput, Optional[GenerateGradingCriterionOutput]]):
    """Generates structured grading instructions."""

    system_message: str = Field(prompt_system_message,
                                description="Message for priming AI behavior and instructing it what to do.")
    human_message: str = Field(prompt_human_message,
                               description="Message from a human. The input on which the AI is supposed to act.")
    tokens_before_split: int = Field(default=2000,
                                     description="Split the grading instructions into file-based ones after this number of tokens.")

    async def process(self, input_data: GenerateGradingCriterionInput, debug: bool, model: ModelConfigType) -> Optional[GenerateGradingCriterionOutput]: # type: ignore
        model = model.get_model() # type: ignore[attr-defined]

        changed_files_from_template_to_solution = get_diff(
            src_repo=input_data.template_repo,
            dst_repo=input_data.solution_repo,
            file_path=None,
            name_only=True
        ).split("\n")

        all_changed_files = load_files_from_repo(
            input_data.solution_repo
        )
        changed_files = {}
        changed_files_content = ""
        for file in changed_files_from_template_to_solution:
            if not file.endswith('.pbxproj'):
                changed_files[file] = get_diff(
                    src_repo=input_data.template_repo,
                    dst_repo=input_data.solution_repo,
                    src_prefix="template",
                    dst_prefix="solution",
                    file_path=file,
                )
                changed_files_content += "\n" + file + ":" + changed_files[file]

        prompt = get_chat_prompt_with_formatting_instructions(
            model=model,
            system_message=self.system_message,
            human_message=self.human_message,
            pydantic_object=GenerateGradingCriterionOutput
        )

        prompt_input = {
            "problem_statement": input_data.problem_statement or "No problem statement.",
            "grading_instructions": input_data.grading_instructions,
            "max_points": input_data.max_points,
            "bonus_points": input_data.bonus_points,
            "template_to_solution_diff": json.dumps(changed_files)
        }

        # Return None if the prompt is too long
        if num_tokens_from_prompt(prompt, prompt_input) > self.max_input_tokens:
            return None

        generate_grading_criterion = await predict_and_parse(
            model=model,
            chat_prompt=prompt,
            prompt_input=prompt_input,
            pydantic_object=GenerateGradingCriterionOutput,
            tags=[
                f"exercise-{input_data.exercise_id}",
                "generate_grading_criterion"
            ]
        )

        if debug:
            emit_meta("generate_grading_criterion", {
                "prompt": prompt.format(**prompt_input),
                "result": generate_grading_criterion.dict() if generate_grading_criterion is not None else None
            })

        if generate_grading_criterion is None or not generate_grading_criterion.structured_grading_criterion:
            return None

        return generate_grading_criterion
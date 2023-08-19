from typing import Optional, Sequence
from athena import emit_meta

from pydantic import BaseModel, Field

from athena.programming import Exercise, Submission

from module_programming_llm.config import BasicApproachConfig
from module_programming_llm.helpers.llm_utils import (
    get_chat_prompt_with_formatting_instructions, 
    num_tokens_from_string, 
    num_tokens_from_prompt, 
    predict_and_parse
)
from module_programming_llm.helpers.utils import get_diff


class FileGradingInstruction(BaseModel):
    file_name: str = Field(..., description="File name")
    grading_instructions: str = Field(..., description="Grading instructions relevant for this file")


class SplitGradingInstructions(BaseModel):
    """Collection of grading instructions split by file"""
    file_grading_instructions: Sequence[FileGradingInstruction] = Field(..., description="File grading instructions")


async def split_grading_instructions_by_file(
        exercise: Exercise, 
        submission: Submission,
        config: BasicApproachConfig, 
        debug: bool
    ) -> Optional[SplitGradingInstructions]:
    """Split the general grading instructions by file

    Args:
        exercise (Exercise): Exercise to split the grading instructions for (respecting the changed files)
        submission (Submission): Submission to split the grading instructions for (respecting the changed files)
        config (BasicApproachConfig): Configuration

    Returns:
        Optional[SplitGradingInstructions]: Split grading instructions, None if it is too short or too long
    """

    # Return None if the grading instructions are too short
    if (exercise.grading_instructions is None 
            or num_tokens_from_string(exercise.grading_instructions) <= config.split_problem_statement_by_file_prompt.tokens_before_split):
        return None
    
    model = config.model.get_model()
    
    template_repo = exercise.get_template_repository()
    solution_repo = exercise.get_solution_repository()
    submission_repo = submission.get_repository()

    changed_files_from_template_to_solution = get_diff(
        src_repo=template_repo, 
        dst_repo=solution_repo, 
        file_path=None, 
        name_only=True
    ).split("\n")

    changed_files_from_template_to_submission = get_diff(
        src_repo=template_repo, 
        dst_repo=submission_repo, 
        file_path=None, 
        name_only=True
    ).split("\n")

    chat_prompt = get_chat_prompt_with_formatting_instructions(
        model=model, 
        system_message=config.split_grading_instructions_by_file_prompt.system_message, 
        human_message=config.split_grading_instructions_by_file_prompt.human_message, 
        pydantic_object=SplitGradingInstructions
    )

    prompt_input = {
        "grading_instructions": exercise.grading_instructions, 
        "changed_files_from_template_to_solution": ", ".join(changed_files_from_template_to_solution),
        "changed_files_from_template_to_submission": ", ".join(changed_files_from_template_to_submission)
    }

    # Return None if the prompt is too long
    if num_tokens_from_prompt(chat_prompt, prompt_input) > config.max_input_tokens:
        return None

    split_grading_instructions = predict_and_parse(
        model=model, 
        chat_prompt=chat_prompt, 
        prompt_input=prompt_input, 
        pydantic_object=SplitGradingInstructions
    )

    if debug:
        emit_meta("file_problem_statement", {
            "prompt": chat_prompt.format(**prompt_input),
            "result": split_grading_instructions.dict()
        })

    if not split_grading_instructions.file_grading_instructions:
        return None

    return split_grading_instructions

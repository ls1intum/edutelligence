from typing import Optional, Sequence
from athena import emit_meta

from pydantic import BaseModel, Field

from athena.programming import Exercise
from athena.storage import store_exercise
from athena.logger import logger

from module_programming_llm.config import BasicApproachConfig
from module_programming_llm.helpers.llm_utils import get_chat_prompt_with_formatting_instructions, num_tokens_from_prompt, predict_and_parse
from module_programming_llm.helpers.utils import get_diff, get_programming_language_file_extension


FILE_GRADING_INSTRUCTIONS_KEY = "file_grading_instructions"


class FileGradingInstruction(BaseModel):
    file_name: str = Field(..., description="File name")
    grading_instructions: str = Field(..., description="Grading instructions relevant for this file")


class SplitGradingInstructions(BaseModel):
    """Collection of grading instructions split by file"""
    instructions: Sequence[FileGradingInstruction] = Field(..., description="File grading instructions")


def split_grading_instructions_by_file(exercise: Exercise, config: BasicApproachConfig, debug: bool) -> SplitGradingInstructions:
    """Split the general grading instructions by file

    Args:
        exercise (Exercise): Exercise to split the grading instructions for
        config (BasicApproachConfig): Configuration

    Returns:
        SplitGradingInstructions: Grading instructions split by file, empty if input was too long
    """
    if exercise.grading_instructions is None or exercise.grading_instructions.strip() == "":
        return SplitGradingInstructions(instructions=[])
    
    model = config.model.get_model()
    
    solution_repo = exercise.get_solution_repository()
    template_repo = exercise.get_template_repository()
    file_extension = get_programming_language_file_extension(exercise.programming_language) or ""
    changed_files = get_diff(src_repo=template_repo, dst_repo=solution_repo, file_path=f"*{file_extension}", name_only=True)

    # logger.info("Exercise: %s", file_extension)
    # logger.info("Changed files: %s", changed_files)
    # logger.info("Solution repo: %s", solution_repo)
    # logger.info("Template repo: %s", template_repo)
    # solution_to_submission_diff = get_diff(src_repo=solution_repo, dst_repo=submission_repo, src_prefix="solution", dst_prefix="submission", file_path=file_path)

    chat_prompt = get_chat_prompt_with_formatting_instructions(
        model=model, 
        system_message=config.split_grading_instructions_by_file_prompt.system_message, 
        human_message=config.split_grading_instructions_by_file_prompt.human_message, 
        pydantic_object=SplitGradingInstructions
    )

    prompt_input = {
        "grading_instructions": exercise.grading_instructions, 
        "changed_files": changed_files
    }

    # If the input is too long, return an empty SplitGradingInstructions object
    prompt_length = num_tokens_from_prompt(chat_prompt, prompt_input)
    if prompt_length > config.max_input_tokens:
        if debug:
            emit_meta(f"{FILE_GRADING_INSTRUCTIONS_KEY}_error", f"Input too long: {prompt_length} > {config.max_input_tokens}")
        return SplitGradingInstructions(instructions=[])

    split_grading_instructions = predict_and_parse(
        model=model, 
        chat_prompt=chat_prompt, 
        prompt_input=prompt_input, 
        pydantic_object=SplitGradingInstructions
    )

    if debug:
        emit_meta(f"{FILE_GRADING_INSTRUCTIONS_KEY}_data", split_grading_instructions.dict())

    return split_grading_instructions


def generate_and_store_split_grading_instructions_if_needed(exercise: Exercise, config: BasicApproachConfig, debug: bool) -> SplitGradingInstructions:
    """Generate and store the split grading instructions if needed

    Args:
        exercise (Exercise): Exercise to get the split grading instructions for
        config (BasicApproachConfig): Configuration

    Returns:
        SplitGradingInstructions: Grading instructions split by file
    """
    if FILE_GRADING_INSTRUCTIONS_KEY in exercise.meta:
        return SplitGradingInstructions.parse_obj(exercise.meta[FILE_GRADING_INSTRUCTIONS_KEY])

    split_grading_instructions = split_grading_instructions_by_file(exercise=exercise, config=config, debug=debug)
    exercise.meta[FILE_GRADING_INSTRUCTIONS_KEY] = split_grading_instructions.dict()
    store_exercise(exercise)
    return split_grading_instructions

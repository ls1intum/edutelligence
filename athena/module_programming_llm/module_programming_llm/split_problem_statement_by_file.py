from typing import Sequence
from athena import emit_meta

from pydantic import BaseModel, Field

from athena.programming import Exercise
from athena.storage import store_exercise

from module_programming_llm.config import BasicApproachConfig
from module_programming_llm.helpers.llm_utils import get_chat_prompt_with_formatting_instructions, num_tokens_from_prompt, predict_and_parse
from module_programming_llm.helpers.utils import get_diff, get_programming_language_file_extension


FILE_PROBLEM_STATEMETS_KEY = "file_problem_statements"


class FileProblemStatement(BaseModel):
    file_name: str = Field(..., description="File name")
    problem_statement: str = Field(..., description="Problem statement relevant for this file")


class SplitProblemStatement(BaseModel):
    """Collection of problem statements split by file"""
    problem_statements: Sequence[FileProblemStatement] = Field(..., description="File problem statements")


def split_problem_statement_by_file(exercise: Exercise, config: BasicApproachConfig, debug: bool) -> SplitProblemStatement:
    """Split the general problem statement by file

    Args:
        exercise (Exercise): Exercise to split the problem statement for
        config (BasicApproachConfig): Configuration

    Returns:
        SplitProblemStatement: Problem statement split by file, empty if input was too long
    """
    if exercise.problem_statement.strip() == "":
        return SplitProblemStatement(problem_statements=[])
    
    model = config.model.get_model()
    
    solution_repo = exercise.get_solution_repository()
    template_repo = exercise.get_template_repository()
    file_extension = get_programming_language_file_extension(exercise.programming_language) or ""
    changed_files = get_diff(src_repo=template_repo, dst_repo=solution_repo, file_path=f"*{file_extension}", name_only=True)

    chat_prompt = get_chat_prompt_with_formatting_instructions(
        model=model, 
        system_message=config.split_problem_statement_by_file_prompt.system_message,
        human_message=config.split_problem_statement_by_file_prompt.system_message,
        pydantic_object=SplitProblemStatement
    )

    prompt_input = {
        "problem_statement": exercise.problem_statement,
        "changed_files": changed_files
    }

    # If the input is too long, return an empty SplitProblemStatement object
    prompt_length = num_tokens_from_prompt(chat_prompt, prompt_input)
    if prompt_length > config.max_input_tokens:
        if debug:
            emit_meta(f"{FILE_PROBLEM_STATEMETS_KEY}_error", f"Input too long: {prompt_length} > {config.max_input_tokens}")
        return SplitProblemStatement(problem_statements=[])

    split_problem_statement = predict_and_parse(
        model=model, 
        chat_prompt=chat_prompt, 
        prompt_input=prompt_input,
        pydantic_object=SplitProblemStatement
    )

    if debug:
        emit_meta(f"{FILE_PROBLEM_STATEMETS_KEY}_data", split_problem_statement.dict())

    return split_problem_statement


def generate_and_store_split_problem_statement_if_needed(exercise: Exercise, config: BasicApproachConfig, debug: bool) -> SplitProblemStatement:
    """Generate and store the split problem statement if needed

    Args:
        exercise (Exercise): Exercise to split the problem statement for
        config (BasicApproachConfig): Configuration

    Returns:
        SplitProblemStatement: Problem statement split by file
    """
    if FILE_PROBLEM_STATEMETS_KEY in exercise.meta:
        return SplitProblemStatement.parse_obj(exercise.meta[FILE_PROBLEM_STATEMETS_KEY])

    split_problem_statement = split_problem_statement_by_file(exercise=exercise, config=config, debug=debug)
    exercise.meta[FILE_PROBLEM_STATEMETS_KEY] = split_problem_statement.dict()
    store_exercise(exercise)
    return split_problem_statement

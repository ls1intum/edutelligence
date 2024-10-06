from typing import Optional, List

from athena.programming import Submission, Exercise, Feedback
from module_programming_llm.config import Configuration
from module_programming_llm.helpers.models import ModelConfigType
from module_programming_llm.prompts import GenerateFileSummary, SplitProblemStatementByFile, \
    SplitGradingInstructionsByFile, GenerateSuggestionsByFile, GenerateSuggestionsByFileOutput
from module_programming_llm.prompts.generate_file_summary import GenerateFileSummaryOutput, GenerateFileSummaryInput
from module_programming_llm.prompts.generate_suggestions_by_file.generate_suggestions_by_file_input import \
    GenerateSuggestionsByFileInput
from module_programming_llm.prompts.split_grading_instructions_by_file import SplitGradingInstructionsByFileOutput, \
    SplitGradingInstructionsByFileInput
from module_programming_llm.prompts.split_problem_statement_by_file import SplitProblemStatementByFileOutput, \
    SplitProblemStatementByFileInput


async def generate_file_summary(step: GenerateFileSummary,
                                input_data: GenerateFileSummaryInput, debug: bool,
                                model: ModelConfigType) -> Optional[GenerateFileSummaryOutput]: # type: ignore[attr-defined]
    return await step.process(input_data, debug, model)


async def split_problem_statement(step: SplitProblemStatementByFile,
                                  input_data: SplitProblemStatementByFileInput, debug: bool,
                                  model: ModelConfigType) -> Optional[SplitProblemStatementByFileOutput]: # type: ignore[attr-defined]
    return await step.process(input_data, debug, model)


async def split_grading_instructions(step: SplitGradingInstructionsByFile,
                                     input_data: SplitGradingInstructionsByFileInput, debug: bool,
                                     model: ModelConfigType) -> Optional[SplitGradingInstructionsByFileOutput]: # type: ignore[attr-defined]
    return await step.process(input_data, debug, model)


async def generate_suggestions(step: GenerateSuggestionsByFile,
                               input_data: GenerateSuggestionsByFileInput, debug: bool,
                               model: ModelConfigType) -> Optional[GenerateSuggestionsByFileOutput]: # type: ignore[attr-defined]
    return await step.process(input_data, debug, model)


async def generate_feedback(exercise: Exercise, submission: Submission, is_graded: bool,
                            module_config: Configuration) -> List[Feedback]: # type: ignore[attr-defined]
    template_repo = exercise.get_template_repository()
    solution_repo = exercise.get_solution_repository()
    submission_repo = submission.get_repository()
    is_debug = module_config.debug
    model = module_config.basic_by_file_approach.model

    generate_file_summary_input = GenerateFileSummaryInput(template_repo, submission_repo, exercise.id, submission.id)
    file_summary_output = await generate_file_summary(module_config.basic_by_file_approach.generate_file_summary,
                                                      generate_file_summary_input, is_debug, model)

    split_grading_instructions_input = SplitGradingInstructionsByFileInput(template_repo, submission_repo,
                                                                           solution_repo, exercise.id, submission.id,
                                                                           exercise.grading_instructions,
                                                                           exercise.grading_criteria)
    split_grading_instructions_output = await split_grading_instructions(
        module_config.basic_by_file_approach.split_grading_instructions_by_file, split_grading_instructions_input,
        is_debug, model)

    split_problem_statement_input = SplitProblemStatementByFileInput(template_repo, submission_repo, solution_repo,
                                                                     exercise.problem_statement, exercise.id,
                                                                     submission.id)
    split_problem_statement_output = await split_problem_statement(
        module_config.basic_by_file_approach.split_problem_statement_by_file, split_problem_statement_input, is_debug,
        model)

    generate_suggestions_input = GenerateSuggestionsByFileInput(template_repo, submission_repo, solution_repo,
                                                                split_grading_instructions_output,
                                                                split_problem_statement_output, exercise.id,
                                                                submission.id, exercise.max_points,
                                                                exercise.bonus_points, exercise.programming_language,
                                                                exercise.grading_criteria, exercise.problem_statement,
                                                                exercise.grading_instructions)
    generate_suggestions_output = await generate_suggestions(
        module_config.basic_by_file_approach.generate_suggestions_by_file, generate_suggestions_input, is_debug, model)

    grading_instruction_ids = set(
        grading_instruction.id
        for criterion in exercise.grading_criteria or []
        for grading_instruction in criterion.structured_grading_instructions
    )

    feedbacks: List[Feedback] = []
    for result in generate_suggestions_output.feedbacks:
        if result is None:
            continue
        grading_instruction_id = (
            result.grading_instruction_id
            if result.grading_instruction_id in grading_instruction_ids
            else None
        )
        feedbacks.append(
            Feedback(
                exercise_id=exercise.id,
                submission_id=submission.id,
                title=result.title,
                description=result.description,
                file_path=result.file_name,
                line_start=result.line_start,
                line_end=result.line_end,
                credits=result.credits,
                structured_grading_instruction_id=grading_instruction_id,
                is_graded=is_graded,
                meta={},
            )
        )

    return feedbacks

from typing import Optional, List

from athena.programming import Submission, Exercise, Feedback
from module_programming_llm.config import Configuration
from module_programming_llm.helpers.models import ModelConfigType
from module_programming_llm.prompts import GenerateFileSummary, SplitProblemStatementByFile, \
    SplitGradingInstructionsByFile, GenerateSuggestionsByFile, GenerateSuggestionsByFileOutput
from module_programming_llm.prompts.filter_out_solution.filter_out_solution import FilterOutSolution
from module_programming_llm.prompts.filter_out_solution.filter_out_solution_input import FilterOutSolutionInput
from module_programming_llm.prompts.filter_out_solution.filter_out_solution_output import FilterOutSolutionOutput
from module_programming_llm.prompts.generate_file_summary import GenerateFileSummaryOutput, GenerateFileSummaryInput
from module_programming_llm.prompts.generate_suggestions_by_file.generate_suggestions_by_file_input import \
    GenerateSuggestionsByFileInput
from module_programming_llm.prompts.split_grading_instructions_by_file import SplitGradingInstructionsByFileOutput, \
    SplitGradingInstructionsByFileInput
from module_programming_llm.prompts.split_problem_statement_by_file import SplitProblemStatementByFileOutput, \
    SplitProblemStatementByFileInput
from module_programming_llm.prompts.validate_suggestions import ValidateSuggestions, ValidateSuggestionsInput, \
    ValidateSuggestionsOutput


async def generate_file_summary(step: GenerateFileSummary,
                                input_data: GenerateFileSummaryInput, debug: bool,
                                model: ModelConfigType) -> (Optional)[GenerateFileSummaryOutput]:  # type: ignore
    return await step.process(input_data, debug, model)


async def split_problem_statement(step: SplitProblemStatementByFile,
                                  input_data: SplitProblemStatementByFileInput, debug: bool,
                                  model: ModelConfigType) -> Optional[SplitProblemStatementByFileOutput]:  # type: ignore
    return await step.process(input_data, debug, model)


async def split_grading_instructions(step: SplitGradingInstructionsByFile,
                                     input_data: SplitGradingInstructionsByFileInput, debug: bool,
                                     model: ModelConfigType) -> Optional[SplitGradingInstructionsByFileOutput]:  # type: ignore
    return await step.process(input_data, debug, model)


async def generate_suggestions(step: GenerateSuggestionsByFile,
                               input_data: GenerateSuggestionsByFileInput, debug: bool,
                               model: ModelConfigType) -> List[Optional[GenerateSuggestionsByFileOutput]]:  # type: ignore
    return await step.process(input_data, debug, model)


async def filter_out_solutions(step: FilterOutSolution,
                               input_data: FilterOutSolutionInput, debug: bool,
                               model: ModelConfigType) -> List[Optional[FilterOutSolutionOutput]]:  # type: ignore
    return await step.process(input_data, debug, model)


async def validate_suggestions(step: ValidateSuggestions,
                               input_data: ValidateSuggestionsInput, debug: bool,
                               model: ModelConfigType) -> List[Optional[ValidateSuggestionsOutput]]:  # type: ignore
    return await step.process(input_data, debug, model)


async def generate_feedback(exercise: Exercise, submission: Submission, is_graded: bool,
                            module_config: Configuration) -> List[Feedback]:  # type: ignore
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
                                                                exercise.id,
                                                                submission.id, exercise.max_points,
                                                                exercise.bonus_points, exercise.programming_language,
                                                                file_summary_output.describe_solution_summary() if file_summary_output else "",
                                                                split_grading_instructions_output,
                                                                split_problem_statement_output,
                                                                exercise.grading_criteria, exercise.problem_statement,
                                                                exercise.grading_instructions)
    output = await generate_suggestions(
        module_config.basic_by_file_approach.generate_suggestions_by_file, generate_suggestions_input, is_debug, model)

    if not is_graded:
        filter_out_solution_input = FilterOutSolutionInput(solution_repo, template_repo, exercise.problem_statement,
                                                           exercise.id, submission.id, output,
                                                           split_problem_statement_output)
        output = await filter_out_solutions(module_config.basic_by_file_approach.filter_out_solution,
                                            filter_out_solution_input, is_debug, model)

    validate_suggestions_input = ValidateSuggestionsInput(solution_repo, template_repo, submission_repo,
                                                          split_problem_statement_output, exercise.problem_statement,
                                                          exercise.id, submission.id, output,
                                                          split_grading_instructions_output, exercise.grading_criteria,
                                                          exercise.grading_instructions,
                                                          file_summary_output.describe_solution_summary() if file_summary_output else "",
                                                          exercise.max_points, exercise.bonus_points,
                                                          exercise.programming_language)
    output = await validate_suggestions(
        module_config.basic_by_file_approach.validate_suggestions, validate_suggestions_input, is_debug, model)

    grading_instruction_ids = set(
        grading_instruction.id
        for criterion in exercise.grading_criteria or []
        for grading_instruction in criterion.structured_grading_instructions
    )

    feedbacks: List[Feedback] = []
    for result in output:
        if result is None:
            continue
        for feedback in result.feedbacks:
            grading_instruction_id = (
                feedback.grading_instruction_id
                if feedback.grading_instruction_id in grading_instruction_ids
                else None
            )
            feedbacks.append(
                Feedback(
                    exercise_id=exercise.id,
                    submission_id=submission.id,
                    title=feedback.title,
                    description=feedback.description,
                    file_path=result.file_path,
                    line_start=feedback.line_start,
                    line_end=feedback.line_end,
                    credits=feedback.credits,
                    structured_grading_instruction_id=grading_instruction_id,
                    is_graded=is_graded,
                    meta={},
                )
            )

    return feedbacks

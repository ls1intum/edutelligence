from typing import List

from athena import emit_meta
from athena.text import Exercise, Submission, Feedback
from athena.logger import logger
from llm_core.utils.llm_utils import (
    check_prompt_length_and_omit_features_if_necessary,
    get_chat_prompt,
    num_tokens_from_prompt,
)
from llm_core.core.predict_and_parse import predict_and_parse

from module_text_llm.chain_of_thought_approach import (
    ChainOfThoughtConfig,
)
from module_text_llm.registry import register_approach
from module_text_llm.helpers.utils import (
    add_sentence_numbers,
    get_index_range_from_line_range,
    format_grading_instructions,
)
from module_text_llm.chain_of_thought_approach.prompt_thinking import (
    InitialAssessmentModel,
)
from module_text_llm.chain_of_thought_approach.prompt_generate_feedback import (
    AssessmentModel,
)


@register_approach("chain_of_thought")
async def generate_suggestions(
    exercise: Exercise,
    submission: Submission,
    config: ChainOfThoughtConfig,
    debug: bool,
    is_graded: bool,
) -> List[Feedback]:

    prompt_input = {
        "max_points": exercise.max_points,
        "bonus_points": exercise.bonus_points,
        "grading_instructions": format_grading_instructions(
            exercise.grading_instructions, exercise.grading_criteria
        ),
        "problem_statement": exercise.problem_statement or "No problem statement.",
        "example_solution": exercise.example_solution,
        "submission": add_sentence_numbers(submission.text),
    }

    chat_prompt = get_chat_prompt(
        system_message=config.thinking_prompt.system_message,
        human_message=config.thinking_prompt.human_message,
    )

    # Check if the prompt is too long and omit features if necessary (in order of importance)
    omittable_features = [
        "example_solution",
        "problem_statement",
        "grading_instructions",
    ]
    prompt_input, should_run = check_prompt_length_and_omit_features_if_necessary(
        prompt=chat_prompt,
        prompt_input=prompt_input,
        max_input_tokens=config.max_input_tokens,
        omittable_features=omittable_features,
        debug=debug,
    )

    # Skip if the prompt is too long
    if not should_run:
        logger.warning("Input too long. Skipping.")
        if debug:
            emit_meta("prompt", chat_prompt.format(**prompt_input))
            emit_meta(
                "error",
                f"Input too long {num_tokens_from_prompt(chat_prompt, prompt_input)} > {config.max_input_tokens}",
            )
        return []

    initial_result = await predict_and_parse(
        model=config.model,
        chat_prompt=chat_prompt,
        prompt_input=prompt_input,
        pydantic_object=InitialAssessmentModel,
        tags=[
            f"exercise-{exercise.id}",
            f"submission-{submission.id}",
        ],
    )

    if initial_result is None:
        return []

    second_prompt_input = {
        "answer": initial_result.dict(),
        "submission": add_sentence_numbers(submission.text),
    }

    second_chat_prompt = get_chat_prompt(
        system_message=config.generate_suggestions_prompt.second_system_message,
        human_message=config.generate_suggestions_prompt.answer_message,
    )

    result = await predict_and_parse(
        model=config.model,
        chat_prompt=second_chat_prompt,
        prompt_input=second_prompt_input,
        pydantic_object=AssessmentModel,
        tags=[
            f"exercise-{exercise.id}",
            f"submission-{submission.id}",
        ],
    )

    if debug:
        emit_meta(
            "generate_suggestions",
            {
                "prompt": chat_prompt.format(**prompt_input),
                "result": result.dict() if result is not None else None,
            },
        )

    if result is None:
        return []

    grading_instruction_ids = set(
        grading_instruction.id
        for criterion in exercise.grading_criteria or []
        for grading_instruction in criterion.structured_grading_instructions
    )

    feedbacks = []
    for feedback in result.feedbacks:
        index_start, index_end = get_index_range_from_line_range(
            feedback.line_start, feedback.line_end, submission.text
        )
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
                index_start=index_start,
                index_end=index_end,
                credits=feedback.credits,
                is_graded=is_graded,
                structured_grading_instruction_id=grading_instruction_id,
                meta={},
            )
        )

    return feedbacks

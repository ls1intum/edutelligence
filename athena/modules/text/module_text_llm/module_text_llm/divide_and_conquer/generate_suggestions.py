import asyncio

from athena.text import Exercise, Submission, Feedback
from athena.logger import logger
from llm_core.core.predict_and_parse import predict_and_parse
from llm_core.utils.llm_utils import get_chat_prompt

from module_text_llm.divide_and_conquer.prompt_generate_suggestions import (
    AssessmentModel,
    FeedbackModel,
    double_curly_braces,
    get_system_prompt,
    get_human_message,
)
from module_text_llm.approach_config import ApproachConfig
from module_text_llm.registry import register_approach
from module_text_llm.helpers.utils import (
    add_sentence_numbers,
    get_index_range_from_line_range,
)


@register_approach("divide_and_conquer")
async def generate_suggestions(
    exercise: Exercise,
    submission: Submission,
    config: ApproachConfig,
    debug: bool,
    is_graded: bool,
) -> list[Feedback]:
    """
    Divide-and-conquer strategy: assess by criterion, concurrently.
    """
    # Prepare text and model
    submission_text = double_curly_braces(submission.text)
    model = config.model.get_model()  # type: ignore[attr-defined]
    prompt_input = {"submission": add_sentence_numbers(submission_text)}

    feedbacks: list[Feedback] = []
    grading_instruction_ids = {
        instr.id
        for crit in exercise.grading_criteria or []
        for instr in crit.structured_grading_instructions
    }
    tasks = []

    # For each criterion, build and dispatch a prompt
    for idx, criterion in enumerate(exercise.grading_criteria or []):
        if criterion.title and "plagiarism" in criterion.title.lower():
            continue  # skip plagiarism checks

        usage_count, system_prompt = get_system_prompt(idx, exercise, criterion)
        chat_prompt = get_chat_prompt(system_prompt, get_human_message())

        processing_inputs = {
            "model": model,
            "chat_prompt": chat_prompt,
            "prompt_input": prompt_input,
            "pydantic_object": FeedbackModel if usage_count == 1 else AssessmentModel,
            "exercise": exercise,
            "submission": submission,
            "grading_instruction_ids": grading_instruction_ids,
            "is_graded": is_graded,
        }
        tasks.append(process_criteria(config, processing_inputs))

    # Execute all criterion assessments in parallel
    results = await asyncio.gather(*tasks)
    for sublist in results:
        feedbacks.extend(sublist)
    return feedbacks


async def process_criteria(
    config: ApproachConfig, processing_inputs: dict
) -> list[Feedback]:
    """
    Run one predict_and_parse call and route to parser.
    """
    try:
        result = await predict_and_parse(
            model=config.model,
            chat_prompt=processing_inputs["chat_prompt"],
            prompt_input=processing_inputs["prompt_input"],
            pydantic_object=processing_inputs["pydantic_object"],
            tags=[
                f"exercise-{processing_inputs['exercise'].id}",
                f"submission-{processing_inputs['submission'].id}",
            ],
        )
    except Exception as e:
        logger.error(
            "LLM call failed for criterion '%s': %s",
            processing_inputs.get("criteria_title"),
            e,
        )
        return []

    # Dispatch parsing based on model type
    if processing_inputs["pydantic_object"] is AssessmentModel:
        try:
            return parse_assessment_result(
                result,
                processing_inputs["exercise"],
                processing_inputs["submission"],
                processing_inputs["grading_instruction_ids"],
                processing_inputs["is_graded"],
            )
        except Exception:
            logger.info("Failed to parse assessment result")
            return []
    else:
        try:
            feedback = parse_feedback_result(
                result,
                processing_inputs["exercise"],
                processing_inputs["submission"],
                processing_inputs["grading_instruction_ids"],
                processing_inputs["is_graded"],
            )
            return [feedback]
        except Exception:
            logger.info("Failed to parse feedback result")
            return []


def parse_assessment_result(
    result, exercise, submission, grading_instruction_ids, is_graded
) -> list[Feedback]:
    feedbacks = []
    for item in result.assessment:
        feedbacks.append(
            parse_feedback_result(
                item, exercise, submission, grading_instruction_ids, is_graded
            )
        )
    return feedbacks


def parse_feedback_result(
    feedback, exercise, submission, grading_instruction_ids, is_graded
) -> Feedback:
    index_start, index_end = get_index_range_from_line_range(
        feedback.line_start, feedback.line_end, submission.text
    )
    struct_id = (
        feedback.assessment_instruction_id
        if feedback.assessment_instruction_id in grading_instruction_ids
        else None
    )
    return Feedback(
        exercise_id=exercise.id,
        submission_id=submission.id,
        title=feedback.criteria,
        description=feedback.feedback,
        index_start=index_start,
        index_end=index_end,
        credits=feedback.credits,
        is_graded=is_graded,
        structured_grading_instruction_id=struct_id,
        meta={},
    )

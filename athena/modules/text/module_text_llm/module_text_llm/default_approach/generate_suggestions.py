from typing import List, Optional

from athena import emit_meta
from athena.schemas import LearnerProfile, Competency
from athena.text import Exercise, Submission, Feedback
from athena.logger import logger

from llm_core.utils.llm_utils import (
    get_chat_prompt,
    check_prompt_length_and_omit_features_if_necessary,
    num_tokens_from_prompt,
)
from llm_core.core.predict_and_parse import predict_and_parse
from module_text_llm.default_approach import DefaultApproachConfig
from module_text_llm.registry import register_approach
from module_text_llm.helpers.utils import (
    add_sentence_numbers,
    get_index_range_from_line_range,
    format_grading_instructions,
)
from module_text_llm.default_approach.schemas import AssessmentModel, SubmissionAnalysis


def _setup_learner_profile(
    learner_profile: Optional[LearnerProfile], 
    config: DefaultApproachConfig
) -> LearnerProfile:
    """Setup and validate learner profile with fallbacks."""
    if learner_profile is None:
        logger.info("Overriding the learner profile with the config from the playground.")
        learner_profile = config.learner_profile

    if learner_profile is None:
        logger.info("Learner profile was not provided - continuing with the default values.")
        learner_profile = LearnerProfile(
            feedback_detail=2,
            feedback_formality=2
        )
    
    return learner_profile


def _prepare_analysis_prompt_input(
    exercise: Exercise,
    submission: Submission,
    latest_submission: Optional[Submission] = None,
    competencies: Optional[List[Competency]] = None,
) -> dict:
    """Prepare input data for the submission analysis prompt."""
    return {
        "max_points": exercise.max_points,
        "bonus_points": exercise.bonus_points,
        "grading_instructions": format_grading_instructions(
            exercise.grading_instructions, exercise.grading_criteria
        ),
        "problem_statement": exercise.problem_statement or "No problem statement.",
        "example_solution": exercise.example_solution,
        "submission": add_sentence_numbers(submission.text),
        "previous_submission": add_sentence_numbers(
            latest_submission.text) if latest_submission is not None else "Previous submission is not available.",
        "competencies": competencies or [],
    }


async def _analyze_submission(
    exercise: Exercise,
    submission: Submission,
    config: DefaultApproachConfig,
    prompt_input: dict,
    debug: bool,
) -> Optional[SubmissionAnalysis]:
    """Perform the first LLM call to analyze the submission."""
    chat_prompt = get_chat_prompt(
        system_message=config.analyze_submission_prompt.system_message,
        human_message=config.analyze_submission_prompt.human_message,
    )

    # Check if the prompt is too long and omit features if necessary (in order of importance)
    omittable_features = [
        "example_solution",
        "problem_statement",
        "grading_instructions",
        "previous_submission",
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
        return None

    submission_analysis: SubmissionAnalysis = await predict_and_parse(
        model=config.model,
        chat_prompt=chat_prompt,
        prompt_input=prompt_input,
        pydantic_object=SubmissionAnalysis,
        tags=[
            f"exercise-{exercise.id}",
            f"submission-{submission.id}",
        ],
    )

    if submission_analysis is None:
        logger.warning("Submission analysis returned None – no feedback generated.")
        return None

    return submission_analysis


async def _generate_feedback(
    exercise: Exercise,
    submission: Submission,
    config: DefaultApproachConfig,
    *,
    submission_analysis: SubmissionAnalysis,
    learner_profile: LearnerProfile,
    debug: bool,
) -> Optional[AssessmentModel]:
    """Perform the second LLM call to generate feedback."""
    second_prompt_input = {
        "example_solution": exercise.example_solution,
        "max_points": exercise.max_points,
        "problem_statement": exercise.problem_statement or "No problem statement.",
        "grading_instructions": format_grading_instructions(exercise.grading_instructions, exercise.grading_criteria),
        "submission": add_sentence_numbers(submission.text),
        "feedback_preferences": learner_profile.get_prompt(),
        "submission_analysis": submission_analysis.dict(),
        "writing_style": learner_profile.get_writing_style_prompt()
    }

    second_chat_prompt = get_chat_prompt(
        system_message=config.generate_suggestions_prompt.system_message,
        human_message=config.generate_suggestions_prompt.human_message,
    )

    # Check if the prompt is too long and omit features if necessary (in order of importance)
    omittable_features = [
        "example_solution",
        "problem_statement",
        "grading_instructions",
        "submission_analysis",
        "writing_style",
        "feedback_preferences",
    ]
    second_prompt_input, should_run = check_prompt_length_and_omit_features_if_necessary(
        prompt=second_chat_prompt,
        prompt_input=second_prompt_input,
        max_input_tokens=config.max_input_tokens,
        omittable_features=omittable_features,
        debug=debug,
    )

    # Skip if the prompt is too long
    if not should_run:
        logger.warning("Input too long. Skipping.")
        if debug:
            emit_meta("prompt", second_chat_prompt.format(**second_prompt_input))
            emit_meta(
                "error",
                f"Input too long {num_tokens_from_prompt(second_chat_prompt, second_prompt_input)} > {config.max_input_tokens}",
            )
        return None

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
                "prompt": second_chat_prompt.format(**second_prompt_input),
                "result": result.dict() if result is not None else None
            }
        )

    return result


def _convert_to_feedback_objects(
    result: AssessmentModel,
    exercise: Exercise,
    submission: Submission,
    is_graded: bool,
) -> List[Feedback]:
    """Convert AssessmentModel to Feedback objects."""
    grading_instruction_ids = set(
        grading_instruction.id
        for criterion in exercise.grading_criteria or []
        for grading_instruction in (criterion.structured_grading_instructions or [])
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
                description=f"{feedback.description}\n\n Next step: {feedback.suggested_action}",
                index_start=index_start,
                index_end=index_end,
                credits=feedback.credits,
                is_graded=is_graded,
                structured_grading_instruction_id=grading_instruction_id,
                meta={},
            )
        )

    return feedbacks


@register_approach("default")
async def generate_suggestions(
    exercise: Exercise,
    submission: Submission,
    config: DefaultApproachConfig,
    *,
    debug: bool,
    is_graded: bool,
    learner_profile: Optional[LearnerProfile],
    latest_submission: Optional[Submission] = None,
    competencies: Optional[List[Competency]] = None,
) -> List[Feedback]:
    """Generate feedback suggestions for a student submission using a two-step LLM approach."""
    if latest_submission is None:
        logger.info("Latest submission is not provided.")

    if competencies is None:
        logger.info("Competencies are not provided.")
    else:
        logger.info("Competencies are provided: %s", competencies)

    # Setup learner profile with fallbacks
    learner_profile = _setup_learner_profile(learner_profile, config)

    # Prepare input for submission analysis
    prompt_input = _prepare_analysis_prompt_input(exercise, submission, latest_submission, competencies)

    # Analyze the submission
    submission_analysis = await _analyze_submission(
        exercise, submission, config, prompt_input, debug
    )
    if submission_analysis is None:
        return []

    # Generate feedback based on analysis
    result = await _generate_feedback(
        exercise=exercise,
        submission=submission,
        config=config,
        submission_analysis=submission_analysis,
        learner_profile=learner_profile,
        debug=debug,
    )
    if result is None:
        return []

    # Convert to Feedback objects
    return _convert_to_feedback_objects(result, exercise, submission, is_graded)

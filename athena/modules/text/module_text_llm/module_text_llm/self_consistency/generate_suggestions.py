from typing import List
import numpy as np

from athena import emit_meta
from athena.text import Exercise, Submission, Feedback
from athena.logger import logger
from llm_core.utils.llm_utils import (
    get_chat_prompt_with_formatting_instructions, 
    check_prompt_length_and_omit_features_if_necessary, 
    num_tokens_from_prompt,
)
from llm_core.utils.predict_and_parse import predict_and_parse
from module_text_llm.approach_config import ApproachConfig
from module_text_llm.helpers.utils import add_sentence_numbers, get_index_range_from_line_range, format_grading_instructions
from module_text_llm.self_consistency.prompt_generate_suggestions import SelfConsistencyModel

async def generate_suggestions(exercise: Exercise, submission: Submission, config: ApproachConfig, debug: bool) -> List[Feedback]:
        
    model = config.model.get_model()  # type: ignore[attr-defined]
    prompt_input = {
        "max_points": exercise.max_points,
        "bonus_points": exercise.bonus_points,
        "grading_instructions": format_grading_instructions(exercise.grading_instructions, exercise.grading_criteria),
        "problem_statement": exercise.problem_statement or "No problem statement.",
        "example_solution": exercise.example_solution,
        "submission": add_sentence_numbers(submission.text)
    }

    chat_prompt = get_chat_prompt_with_formatting_instructions(
        model=model, 
        system_message=config.generate_suggestions_prompt.system_message, 
        human_message=config.generate_suggestions_prompt.human_message, 
        pydantic_object=SelfConsistencyModel
    )

    # Check if the prompt is too long and omit features if necessary (in order of importance)
    omittable_features = ["example_solution", "problem_statement", "grading_instructions"]
    prompt_input, should_run = check_prompt_length_and_omit_features_if_necessary(
        prompt=chat_prompt,
        prompt_input= prompt_input,
        max_input_tokens=config.max_input_tokens,
        omittable_features=omittable_features,
        debug=debug
    )

    # Skip if the prompt is too long
    if not should_run:
        logger.warning("Input too long. Skipping.")
        if debug:
            emit_meta("prompt", chat_prompt.format(**prompt_input))
            emit_meta("error", f"Input too long {num_tokens_from_prompt(chat_prompt, prompt_input)} > {config.max_input_tokens}")
        return []

    result = await predict_and_parse(
        model=model, 
        chat_prompt=chat_prompt, 
        prompt_input=prompt_input, 
        pydantic_object=SelfConsistencyModel,
        tags=[
            f"exercise-{exercise.id}",
            f"submission-{submission.id}",
        ],
        use_function_calling=True
    )

    if debug:
        emit_meta("generate_suggestions", {
            "prompt": chat_prompt.format(**prompt_input),
            "result": result.dict() if result is not None else None
        })

    if result is None:
        return []

    grading_instruction_ids = set(
        grading_instruction.id 
        for criterion in exercise.grading_criteria or [] 
        for grading_instruction in criterion.structured_grading_instructions
    )
    summary = summarize_assessments(result)
    for item in summary:
        print(item)
    # print(result)calculate_weighted_consistency(ultra_feedbacks, (0.8, 0.2))
    chosen_feedback = result.self_consistency_list [calculate_weighted_consistency(result.self_consistency_list)]
    
    print(chosen_feedback)
    # for feedback_list in result.self_consistency_list:
    feedbacks = []
    for feedback in chosen_feedback.feedbacks:
        index_start, index_end = get_index_range_from_line_range(feedback.line_start, feedback.line_end, submission.text)
        grading_instruction_id = feedback.grading_instruction_id if feedback.grading_instruction_id in grading_instruction_ids else None
        feedbacks.append(Feedback(
            exercise_id=exercise.id,
            submission_id=submission.id,
            title=feedback.title,
            description=feedback.description,
            index_start=index_start,
            index_end=index_end,
            credits=feedback.credits,
            structured_grading_instruction_id=grading_instruction_id,
            meta={}
        ))
            
    return feedbacks
from typing import List, Dict

def summarize_assessments(self_consistency_model: SelfConsistencyModel) -> List[Dict[str, str]]:
    summaries = []
    
    for i, assessment in enumerate(self_consistency_model.self_consistency_list):
        total_credits = sum(feedback.credits for feedback in assessment.feedbacks)
        grading_instruction_ids = [feedback.grading_instruction_id for feedback in assessment.feedbacks if feedback.grading_instruction_id is not None]
        
        summary = {
            "Assessment": f"Assessment {i+1}",
            "Total Credits": total_credits,
            "Grading Instruction IDs": grading_instruction_ids
        }
        
        summaries.append(summary)
    
    return summaries

def calculate_weighted_consistency(feedbacks_list):
    """
    Calculate the self-consistency score for feedback options based on credit sums.

    Parameters:
    feedbacks_list (list of AssessmentModel): A list of AssessmentModel instances.

    Returns:
    int: Index of the assessment with the lowest absolute difference from the mean of credit sums.
    """
    total_credits = [sum(feedback.credits for feedback in assessment.feedbacks) for assessment in feedbacks_list]
    mean_credits = np.mean(total_credits)
    
    # Calculate the absolute difference from the mean for each assessment
    differences = [(i, abs(credits - mean_credits)) for i, credits in enumerate(total_credits)]
    
    # Sort by the smallest difference and return the index of the best score
    differences.sort(key=lambda x: x[1])
    print("XXXXXXXXXXXXX")
    print(differences)
    print("XXXXXXXXXXXXX")
    return differences[0][0]

from typing import List
from athena import emit_meta
from athena.text import Exercise, Submission, Feedback
from athena.logger import logger
from llm_core.utils.llm_utils import get_simple_chat_prompt,get_chat_prompt_with_formatting_instructions,get_chat_prompt_with_formatting_instructions_2
from llm_core.utils.predict_and_parse import predict_and_parse
from module_text_llm.best_approach.prompt_generate_suggestions import AssessmentModel, FeedbackModel
from module_text_llm.approach_config import ApproachConfig
from module_text_llm.helpers.utils import add_sentence_numbers, get_index_range_from_line_range, format_grading_instructions
import asyncio
import re
def double_curly_braces(input_str):
    # Curly braces are used as placeholders in the prompt, so we need to escape them if found in the text
    return input_str.replace("{", " ").replace("}", " ")
    # return re.sub(r"({|})", r"\1\1", input_str)

    # return input_str.replace("{", "{{").replace("}", "}}")
# Placeholder for generate suggestions logic.
async def generate_suggestions(exercise: Exercise, submission: Submission, config: ApproachConfig, debug: bool, is_graded: bool):
    submission_text = double_curly_braces(submission.text)
    model = config.model.get_model()  # type: ignore[attr-defined]
    prompt_input = {
        "submission": add_sentence_numbers(submission_text)
    }

    grading_criteria = exercise.grading_criteria
    feedbacks = []
    grading_instruction_ids = set(
        grading_instruction.id 
        for criterion in exercise.grading_criteria or [] 
        for grading_instruction in criterion.structured_grading_instructions
    )
    tasks = []
    for idx, criteria in enumerate(grading_criteria):
        if(criteria.title == "Plagiarism" or criteria.title == "plagiarism"): # Exclude plagarism becase the model cannot know and it hallucinates
            continue
        criteria_explanation_prompt = f"You are an AI Assistant TUTOR at a prestigious university tasked with assessing text submissions. You are tasked with assessing a submission from a student. The problem statement is:"
        problem_statement = f"""
        # Problem Statement 
         {double_curly_braces(exercise.problem_statement)}.
        # End Problem Statement
        A sample solution to the problem statement is:
        # Example Solution
        {double_curly_braces(exercise.example_solution)}
        # End Example Solution
        # General Instructions
        You do not have access to lecture materials, exercise sheet or otherwise. If any criteria or instruction requires you to have this knowledge do not make any assumptions, such examples would include plagrarism, examples from lectures etc..
        # End General Instructions"""
        
        criteria_explanation_prompt += problem_statement
        # Handle Arbitrarily often criteria, this is denoted by 0

        criteria_explanation_prompt += f""" 
        You have to assess the submission based on the criteria with the title: "{criteria.title}". There are
        {len(criteria.structured_grading_instructions)} structured assessment instructions options for this criteria.
        """
        usage_counts = [instruction.usage_count for instruction in criteria.structured_grading_instructions]
        use_same_usaged_count = False
        if(len(set(usage_counts)) == 1):
            use_same_usaged_count = True
        if use_same_usaged_count:
            criteria_explanation_prompt += f""" 
            {get_criteria_application(usage_counts)}.
            The structured assessment instructions are as follows: \n"""
        for idx,instruction in enumerate(criteria.structured_grading_instructions):
            criteria_explanation_prompt += f""" 
            Instruction Number {idx+1}: Apply {instruction.credits} credits if the following description fits the students submission: "{instruction.instruction_description}. A possible feedback could be in the likes of "{instruction.feedback}" but you may adjust it as you see fit. Apply assessment instruction id {instruction.id} to this segment of the submission. \n
            """
        if(usage_counts[0] > 1):
            chat_prompt = get_chat_prompt_with_formatting_instructions(model = model, system_message = criteria_explanation_prompt,human_message = "Now you must assess the following student submission. The student submission:\n {submission}",pydantic_object = AssessmentModel)
            tasks.append(process_criteria(AssessmentModel, model, chat_prompt, prompt_input, exercise, submission, grading_instruction_ids, is_graded,criteria.title))
        else:
            chat_prompt = get_chat_prompt_with_formatting_instructions(model = model, system_message = criteria_explanation_prompt,human_message = "Now you must assess the following student submission. The student submission:\n {submission}",pydantic_object = FeedbackModel)
            tasks.append(process_criteria(FeedbackModel, model, chat_prompt, prompt_input, exercise, submission, grading_instruction_ids, is_graded,criteria.title))
    results = await asyncio.gather(*tasks)

    # Flatten the list of feedbacks
    for feedback_list in results:
        feedbacks += feedback_list
    print(feedbacks)
    return feedbacks
async def process_criteria(pydantic_object, model, chat_prompt, prompt_input, exercise, submission, grading_instruction_ids, is_graded,criteria_title):
    # Call the predict_and_parse method
    result = await predict_and_parse(
        model=model, 
        chat_prompt=chat_prompt, 
        prompt_input=prompt_input, 
        pydantic_object=pydantic_object,
        tags=[
            f"exercise-{exercise.id}",
            f"submission-{submission.id}",
        ],
        use_function_calling=True
    )

    if pydantic_object is AssessmentModel:
        try:
            return parse_assessment_result(result, exercise, submission, grading_instruction_ids, is_graded,criteria_title)
        except Exception as e:
            return []
    else:
        try:
            return parse_feedback_result(result, exercise, submission, grading_instruction_ids, is_graded,criteria_title)
        except Exception as e:
            return []

def parse_assessment_result(result, exercise, submission, grading_instruction_ids, is_graded,criteria_title):
    result_feedbacks = []
    for feedback in result.assessment:
        result_feedbacks += parse_feedback_result(feedback, exercise, submission, grading_instruction_ids, is_graded,criteria_title)
    return result_feedbacks

def parse_feedback_result(feedback, exercise, submission, grading_instruction_ids, is_graded,criteria_title):
    result_feedbacks = []

    index_start, index_end = get_index_range_from_line_range(
        feedback.line_start, feedback.line_end, submission.text
    )
    assessment_instruction_id = (
        feedback.assessment_instruction_id 
        if feedback.assessment_instruction_id in grading_instruction_ids 
        else None
    )
    result_feedbacks.append(Feedback(
        exercise_id=exercise.id,
        submission_id=submission.id,
        title=feedback.criteria,
        description=feedback.feedback,
        index_start=index_start,
        index_end=index_end,
        credits=feedback.credits,
        is_graded=is_graded,
        structured_grading_instruction_id=assessment_instruction_id,
        meta={}
    ))
    return result_feedbacks


def get_criteria_application(usage_counts):
    usaged_count_prompt = ""
    if usage_counts[0] == 0:
        usaged_count_prompt = "You may apply this criteria as many times as it is needed if it fits the submission."
    elif usage_counts[0] == 1:
        usaged_count_prompt = "You may only apply this criteria ONCE. You must pick the instruction that best fits the submission. "
    else:
        usaged_count_prompt = f"You may apply thic criteria {usage_counts[0]} times. Each time must pick the instruction that best fits the submission."
    
    usaged_count_prompt += """ For this criteria you have different levels of assessment to give, based on the structured assessment instructions."""
    usaged_count_prompt += """For different segments of the submission you may apply a different assessment instruction that is fitting to that segment and give it its respective deserved credits. 
    Identify all segments of the submission that relate to this criteria and its instructions and apply the correct feedback as described by the instructions. 
    Keep in mind that the student might seperate his answers throught the whole submission. 
    """ if usage_counts[0] != 1 else "You may apply this criteria only once and choose only a SINGLE assessment instruciton that best fits the submission!"
    return usaged_count_prompt

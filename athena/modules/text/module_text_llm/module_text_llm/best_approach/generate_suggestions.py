from typing import List
from athena import emit_meta
from athena.text import Exercise, Submission, Feedback
from athena.logger import logger
from llm_core.utils.llm_utils import get_simple_chat_prompt
from llm_core.utils.predict_and_parse import predict_and_parse
from module_text_llm.best_approach.prompt_generate_suggestions import AssessmentModel
from module_text_llm.approach_config import ApproachConfig
from module_text_llm.helpers.utils import add_sentence_numbers, get_index_range_from_line_range, format_grading_instructions
import asyncio

# Placeholder for generate suggestions logic.
async def generate_suggestions(exercise: Exercise, submission: Submission, config: ApproachConfig, debug: bool, is_graded: bool):
    model = config.model.get_model()  # type: ignore[attr-defined]
    prompt_input = {
        # "max_points": exercise.max_points,
        # "bonus_points": exercise.bonus_points,
        # "grading_instructions": format_grading_instructions(exercise.grading_instructions, exercise.grading_criteria),
        # "problem_statement": exercise.problem_statement or "No problem statement.",
        # "example_solution": exercise.example_solution,
        "submission": add_sentence_numbers(submission.text)
    }
    # Let us define our beatiful steps.
    # For now assuming using gpt4o
    
    # Nr1. Seperate the grading criteria.
    grading_criteria = exercise.grading_criteria
    # print(grading_criteria)
    feedbacks = [] # Multi calling. Or use history
    grading_instruction_ids = set(
        grading_instruction.id 
        for criterion in exercise.grading_criteria or [] 
        for grading_instruction in criterion.structured_grading_instructions
    )
    tasks = []
    for idx, criteria in enumerate(grading_criteria):
        criteria_explanation_prompt = f"You are tasked with assessing a submission from a student. The problem statement is:"
        problem_statement = f"""
        # Problem Statement 
         {exercise.problem_statement}.
        # End Problem Statement
        A sample solution to the problem statement is:
        # Example Solution
        {exercise.example_solution}
        # End Example Solution"""
        criteria_explanation_prompt += problem_statement
        # print(criteria)
        # print(type(criteria))
        # print(criteria.title)
        criteria_explanation_prompt += f""" 
        You have to assess the submission based on the criteria with the title: "{criteria.title}". There are
        {len(criteria.structured_grading_instructions)} structured grading instructions options for this criteria.
        """
        # print(criteria.id)
        # print(criteria) # should be a list
        
        usage_counts = [instruction.usage_count for instruction in criteria.structured_grading_instructions]
        use_same_usaged_count = False
        if(len(set(usage_counts)) == 1):
            use_same_usaged_count = True
        if use_same_usaged_count:
            criteria_explanation_prompt += f""" 
            This criteria can be applied {usage_counts[0]} {"times" if usage_counts[0] > 1 else "time"}.
            For this criteria you have different levels of assessment to give, based on the structured grading instructions.
            {"For different segments of the submission you may apply a different grading instruction that is fitting to that segment. Identify all segments of the submission that relate to this criteria and its instructions. Keep in mind that the student might seperate his answers throught the whole submission. If they are missing but were neccessary indicate this on your feedback with 0 credits." if usage_counts[0] > 1 else "You may apply this criteria only once!"}
            The structured grading instructions are as follows: \n"""
        for idx,instruction in enumerate(criteria.structured_grading_instructions):
            criteria_explanation_prompt += f""" 
            Instruction Number {idx+1}: You must award {instruction.credits} credits if the following description applies: "{instruction.instruction_description=}. A possible feedback could be in the likes of "{instruction.feedback}" but you may adjust it as you see fit. Apply grading instruction id {instruction.id} to this segment of the submission. \n
            """
        # print(criteria_explanation_prompt)
        # criteria_explanation_prompt += f""" """ 3
        chat_prompt = get_simple_chat_prompt(criteria_explanation_prompt,"Here is the submission: {submission}")
        tasks.append(process_criteria(criteria, model, chat_prompt, prompt_input, exercise, submission, grading_instruction_ids, is_graded))
        # result = await predict_and_parse(
        #     model=model, 
        #     chat_prompt=chat_prompt, 
        #     prompt_input=prompt_input, 
        #     pydantic_object=AssessmentModel,
        #     tags=[
        #         f"exercise-{exercise.id}",
        #         f"submission-{submission.id}",
        #     ],
        #     use_function_calling=True
        # )
        
        # result_feedbacks = []
        # for feedback in result.feedbacks:
        #     index_start, index_end = get_index_range_from_line_range(feedback.line_start, feedback.line_end, submission.text)
        #     grading_instruction_id = feedback.grading_instruction_id if feedback.grading_instruction_id in grading_instruction_ids else None
        #     result_feedbacks.append(Feedback(
        #         exercise_id=exercise.id,
        #         submission_id=submission.id,
        #         title=feedback.title,
        #         description=feedback.description,
        #         index_start=index_start,
        #         index_end=index_end,
        #         credits=feedback.credits,
        #         is_graded=is_graded,
        #         structured_grading_instruction_id=grading_instruction_id,
        #         meta={}
        #     ))
        # feedbacks+=result_feedbacks
    results = await asyncio.gather(*tasks)

    # Flatten the list of feedbacks
    for feedback_list in results:
        feedbacks += feedback_list
    return feedbacks

async def process_criteria(criteria, model, chat_prompt, prompt_input, exercise, submission, grading_instruction_ids, is_graded):
    # Call the predict_and_parse method
    result = await predict_and_parse(
        model=model, 
        chat_prompt=chat_prompt, 
        prompt_input=prompt_input, 
        pydantic_object=AssessmentModel,
        tags=[
            f"exercise-{exercise.id}",
            f"submission-{submission.id}",
        ],
        use_function_calling=True
    )
    
    # Parse feedbacks
    result_feedbacks = []
    for feedback in result.feedbacks:
        index_start, index_end = get_index_range_from_line_range(
            feedback.line_start, feedback.line_end, submission.text
        )
        grading_instruction_id = (
            feedback.grading_instruction_id 
            if feedback.grading_instruction_id in grading_instruction_ids 
            else None
        )
        result_feedbacks.append(Feedback(
            exercise_id=exercise.id,
            submission_id=submission.id,
            title=feedback.title,
            description=feedback.description,
            index_start=index_start,
            index_end=index_end,
            credits=feedback.credits,
            is_graded=is_graded,
            structured_grading_instruction_id=grading_instruction_id,
            meta={}
        ))
    return result_feedbacks
import json
from typing import List
from langchain.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from langchain_core.messages import BaseMessage
from langchain.output_parsers import PydanticOutputParser

from module_text_llm.helpers.utils import format_grading_instructions, add_sentence_numbers, \
    get_line_range_from_index_range
from module_text_llm.text_evaluation.evaluation_schemas import Exercise, Submission, Feedback, Metric, MetricEvaluations

system_message = """
You are a computer science professor overseeing multiple tutors who assist in grading student assignments. Your task is to evaluate the quality of feedback provided by these tutors to ensure it meets high standards.

You will be provided with the following:
**1. Problem Description**: A description of the problem assigned to the student.
**2. Model Solution**: A sample solution that represents an ideal response to the problem.
**3. Grading Instructions**: A set of guidelines that tutors must follow when grading submissions.
**4. Feedback Criteria**: A list of criteria based on which the feedback should be evaluated.

Additionally, you will be provided with the following:
**5. Student Submission**: The response submitted by the student.
**6. Tutor Feedback**: The feedback given by the tutor to the student.

# 1. Problem Description:
{problem_statement}

# 2. Model Solution:
{example_solution}

# 3. Grading Instructions:
{grading_instructions}

# 4. Feedback Criteria:
{metrics}

# Your Task:
Evaluate the tutor’s feedback based on the criteria. For each criterion, rate the feedback on a scale from 1 (worst) to 5 (best).
{format_instructions}

Do **not** provide comments. Focus on adhering strictly to the problem description and the criteria.
"""

human_message = """
# 5. Student Submission:
{submission}

# 6. Tutor Feedback:
{feedbacks}
"""


def get_formatted_prompt(exercise: Exercise, submission: Submission, feedbacks: List[Feedback], metrics: List[Metric]) -> List[BaseMessage]:
    output_parser = PydanticOutputParser(pydantic_object=MetricEvaluations)

    def feedback_to_dict(exercise: Exercise, feedback: Feedback, submission: Submission):
        line_start, line_end = get_line_range_from_index_range(feedback.index_start, feedback.index_end,
                                                               submission.text)
        grading_instruction_feedback = ""
        if feedback.structured_grading_instruction_id:
            grading_instructions = {
                instruction.id: instruction
                for criterion in (exercise.grading_criteria or [])
                for instruction in (criterion.structured_grading_instructions or [])
            }
            grading_instruction = grading_instructions.get(feedback.structured_grading_instruction_id)
            grading_instruction_feedback = grading_instruction.feedback + ": " if grading_instruction else None

        return {
            "description": grading_instruction_feedback + feedback.description,
            "line_start": line_start,
            "line_end": line_end,
            "structured_grading_instruction_id": feedback.structured_grading_instruction_id,
        }

    prompt_input = {
        "problem_statement": exercise.problem_statement or "No problem statement.",
        "example_solution": exercise.example_solution,
        "grading_instructions": format_grading_instructions(exercise.grading_instructions, exercise.grading_criteria),
        "metrics": json.dumps([metric.dict() for metric in metrics]),
        "format_instructions": output_parser.get_format_instructions(),
        "submission": add_sentence_numbers(submission.text),
        "feedbacks": json.dumps([feedback_to_dict(exercise, feedback, submission) for feedback in feedbacks]),
    }

    system_message_prompt = SystemMessagePromptTemplate.from_template(system_message)
    human_message_prompt = HumanMessagePromptTemplate.from_template(human_message)

    chat_prompt_template = ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])

    return chat_prompt_template.format_prompt(**prompt_input).to_messages()
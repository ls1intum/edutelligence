import json
from typing import List, Optional
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import PydanticOutputParser

from model.evaluation_model import Metric, MetricEvaluations
from model.model import (
    Exercise,
    Submission,
    Feedback,
    GradingCriterion,
)

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
Evaluate the tutor’s feedback based on the criteria. For each criterion, rate the feedback on a scale from 1 (strongly disagree) to 5 (strongly agree). If you can not evaluate a criterion, rate it 0 (not ratable).
{format_instructions}

Do **not** provide comments. Focus on adhering strictly to the problem description and the criteria.
"""

human_message = """
# 5. Student Submission:
{submission}

# 6. Tutor Feedback:
{feedbacks}
"""


def format_metrics(metrics: List[Metric]) -> str:
    """Formats metrics into a single string.

    Args:
        metrics (List[Metric]): List of metrics

    Returns:
        str: Formatted metrics
    """

    if not metrics:
        return "No metrics provided."

    result = ""
    for index, metric in enumerate(metrics, start=1):
        result += f"{index}) {metric.title}:\n"
        result += f"summary: {{{metric.summary}}}\n"
        result += f"description: {{\n{metric.description}\n}}\n"

    return result.strip()


def format_grading_instructions(
    grading_instructions: Optional[str],
    grading_criteria: Optional[List[GradingCriterion]],
) -> Optional[str]:
    """Formats grading instructions and the grading criteria with nested structured grading instructions into a single string.

    Args:
        grading_instructions (Optional[str]): Grading instructions
        grading_criteria (Optional[List[GradingCriterion]]): Grading criteria with nested structured grading instructions

    Returns:
        Optional[str]: Formatted grading instructions or None if no grading instructions or grading criteria are provided
    """

    if not grading_instructions and not grading_criteria:
        return None

    result = ""
    if grading_instructions:
        result += grading_instructions + "\n\n"

    if grading_criteria:
        for grading_criterion in grading_criteria:
            result += (
                f'Criterion > "{(grading_criterion.title or "Unnamed criterion")}":\n'
            )
            for (
                grading_instruction
            ) in grading_criterion.structured_grading_instructions:
                result += f'  - grading_instruction_id={grading_instruction.id} > "{grading_instruction.feedback}": ('
                if grading_instruction.usage_count > 0:
                    result += (
                        f"can be used {grading_instruction.usage_count} times in total"
                    )
                else:
                    result += "can be used unlimited times"
                result += f', gives {grading_instruction.credits} credits for "{grading_instruction.grading_scale}" grading scale, '
                result += f'usage description: "{grading_instruction.instruction_description}")\n'
            result += "\n"

    return result.strip()


def get_formatted_prompt(
    exercise: Exercise,
    submission: Submission,
    feedbacks: List[Feedback],
    metrics: List[Metric],
) -> List[BaseMessage]:
    output_parser = PydanticOutputParser(pydantic_object=MetricEvaluations)

    def feedback_to_dict(
        exercise: Exercise, feedback: Feedback, submission: Submission
    ):
        referenced_text = submission.text[feedback.index_start : feedback.index_end]

        grading_instruction_feedback = ""
        if feedback.structured_grading_instruction_id:
            grading_instructions = {
                instruction.id: instruction
                for criterion in (exercise.grading_criteria or [])
                for instruction in (criterion.structured_grading_instructions or [])
            }
            grading_instruction = grading_instructions.get(
                feedback.structured_grading_instruction_id
            )
            grading_instruction_feedback = (
                grading_instruction.feedback + ": " if grading_instruction else None
            )

        return {
            "description": f"{grading_instruction_feedback}\n{feedback.description}",
            "referenced_text": referenced_text,
            "structured_grading_instruction_id": feedback.structured_grading_instruction_id,
        }

    prompt_input = {
        "problem_statement": exercise.problem_statement or "No problem statement.",
        "example_solution": exercise.example_solution or "No example solution.",
        "grading_instructions": format_grading_instructions(
            exercise.grading_instructions, exercise.grading_criteria
        ),
        "metrics": format_metrics(metrics),
        "format_instructions": output_parser.get_format_instructions(),
        "submission": submission.text,
        "feedbacks": json.dumps(
            [feedback_to_dict(exercise, feedback, submission) for feedback in feedbacks]
        ),
    }

    system_message_prompt = SystemMessagePromptTemplate.from_template(system_message)
    human_message_prompt = HumanMessagePromptTemplate.from_template(human_message)

    chat_prompt_template = ChatPromptTemplate.from_messages(
        [system_message_prompt, human_message_prompt]
    )

    return chat_prompt_template.format_prompt(**prompt_input).to_messages()

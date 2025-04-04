from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum

system_message = """
         You gave the following feedback on the first iteration: {answer}
         On this step you need to refine your feedback. You will recieve the student submission once more.
         Make sure to follow the following steps to assess and improve your feedback:
         - Credits given or deducted should be consistent and tracable to the grading instructions and the sample solution, if it doesn't, consider improvements.
         - If you have your own additional improvements that are not present in the grading instructions, add them in a new feedback with 0 credits and no reference.
         - Remember that your response is directly seen by students and it should adress them directly.
         - For each feedback where the student has room for improvement, think about how the student could improve his solution.
         - Once you have thought how the student can improve the solution, formulate it in a way that guides the student towards the correct solution without revealing it directly.
         - References should not overlap, that means that no two feedback must have overlaping line_start and line_end.
         - If the feedback is general and not related to a specific line, leave line_start and line_end empty.
         - Consider improvements to the feedback if any of this points is not satisfied.
         - Encourage reflection and critical thinking by asking open-ended follow-up questions.
         - Consider the following preferences by the student:

            - Practical vs. Theoretical - {practical_theoretical}
                - Theoretical - Emphasizes abstract concepts, definitions, and explanations.
                - Practical - Focuses on examples, applications, and concrete use cases.
                - 0 would mean practical, 2 theoretical, and 1 in between
            - Creative Exploration vs. Focused Guidance - {creative_guidance}
                - Creative Exploration - Offers prompts or hints that nudge students toward considering multiple possible approaches or perspectives - like, Can you think of a way to solve this using recursion instead of iteration?
                - Focused Guidance - Keeps the feedback aligned with the most straightforward or expected line of reasoning, helping the student deepen understanding of a single clear path - without necessarily labeling it as standard.
                - 0 would mean creatively explorative, 2 guidance focused, and 1 in between
            - Follow up questions vs Summary, Conclusion - {followup_summary}
                - Follow-up Questions - Promotes active learning by prompting the student to think further, reflect, or apply the concept elsewhere.
                - Summary, Conclusion - Provides a clear takeaway or wrap-up to consolidate what has been learned, with no further prompting.
                - 0 would mean more follow up questions, 2 summary and conclusions, and 1 in between
            - Brief vs. Detailed - {brief_detailed}
                - Brief - Keeps feedback short and to the point - good for advanced students or when cognitive load is high.
                - Detailed - Provides more background, context, and elaboration - ideal for beginners or when encountering a new concept.
                - 0 would mean brief, 2 detailed, and 1 in between 
    
         You will be provided once again with the student submission.
         Respond in json

         """

human_message = """\
Student\'s submission to grade (with sentence numbers <number>: <sentence>):
\"\"\"
{submission}
\"\"\"\
"""


# Input Prompt

class GenerateSuggestionsPrompt(BaseModel):
    """\
Features cit available: **{problem_statement}**, **{example_solution}**, **{grading_instructions}**, **{max_points}**, **{bonus_points}**, **{submission}**, **{practical_theoretical}**, **{creative_guidance}**, **{followup_summary}**, **{brief_detailed}**

_Note: **{problem_statement}**, **{example_solution}**, or **{grading_instructions}** might be omitted if the input is too long._\
"""
    second_system_message: str = Field(default=system_message,
                                       description="Message for priming AI behavior and instructing it what to do.")
    answer_message: str = Field(default=human_message,
                                description="Message from a human. The input on which the AI is supposed to act.")


# Output Object

class FeedbackType(str, Enum):
    referenced = "referenced"
    unreferenced = "unreferenced"


class UnreferencedFeedbackType(str, Enum):
    follow_up_question = "follow_up_question"
    alternative_answer = "alternative_answer"
    hint_for_mistake = "hint_for_mistake"


class FeedbackModel(BaseModel):
    title: str = Field(description="Very short title, i.e. feedback category or similar", example="Logic Error")
    description: str = Field(description="Feedback description")
    feedback_type: FeedbackType = Field(
        description="Feedback type, if referenced if it reference to a line number start and end, unreferenced otherwise"
    )
    unreferenced_feedback_type: Optional[UnreferencedFeedbackType] = Field(description="Type of the unreferenced feedback")
    line_start: Optional[int] = Field(description="Referenced line number start, or empty if unreferenced")
    line_end: Optional[int] = Field(description="Referenced line number end, or empty if unreferenced")
    credits: float = Field(0.0, description="Number of points received/deducted")
    grading_instruction_id: Optional[int] = Field(
        description="ID of the grading instruction that was used to generate this feedback, or empty if no grading instruction was used"
    )


class AssessmentModel(BaseModel):
    """Collection of feedbacks making up an assessment"""

    feedbacks: List[FeedbackModel] = Field(description="Assessment feedbacks")

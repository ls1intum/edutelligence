from pydantic import BaseModel


class FilterFeedbackInputs(BaseModel):
    original_feedback: str
    feedback_output_format: str

filter_feedback_system_message = """
Your task is to modify given feedback. This feedback was originally created for tutors to help them grade student submissions. We want to use this same feedback for students before the due date of the assignment. However we need to make sure that the feedback does not give away the solution. Your task is to modify the feedback so that it is appropriate for students.

Follow these guidelines when filtering and rewriting the feedback:

- Avoid revealing specific solutions or correct answers.
- Focus on providing general guidance and encouragement.
- Highlight areas that need improvement without giving away the solution.
- Maintain a positive and constructive tone.
- Provide hints or suggestions rather than direct corrections.
- Keep the feedback concise and to the point.
- Ensure that the feedback is still relevant and helpful for the student's learning process.

Keep the original structure, just change the title and description of the feedback

For example, original feedback:
"title": "Missing Start Event"
"description": "The process is missing the start event"
...

Filtered and rewritten feedback:
"title": "Process Initiation"
"description": "Consider how your process begins. Is there a clear starting point? Review the standard elements used to indicate the commencement of a process flow."
...

Remember, the goal is to guide the student towards improvement without providing a complete solution or grading information in the feedback. Also keep the original structure of the feedback. Just modify the title and description values.

<Output Format>
{feedback_output_format}
"""

filter_feedback_human_message = """
<Original Graded Feedback>
{original_feedback}

Please return the feedback in the correct output json format:
"""
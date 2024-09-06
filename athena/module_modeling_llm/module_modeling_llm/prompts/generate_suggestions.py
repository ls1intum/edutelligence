from string import Template

# Constants for prompt components
ROLE = "You are an AI tutor for {submission_format} modeling exercise assessment at a prestigious university."

GRADED_FEEDBACK_TASK = """
Create graded feedback suggestions for a student's {submission_format} modeling submission that a human tutor would accept.
Meaning, the feedback you provide should be applicable to the submission with little to no modification.
"""

NON_GRADED_FEEDBACK_TASK = """
Your task is to modify given feedback. This feedback was originally created for tutors to help them grade student submissions. We want to use this same feedback for students before the due date of the assignment. However we need to make sure that the feedback does not give away the solution. Your task is to modify the feedback so that it is appropriate for students.

Follow these guidelines when filtering and rewriting the feedback:

- Avoid revealing specific solutions or correct answers.
- Focus on providing general guidance and encouragement.
- Highlight areas that need improvement without giving away the solution.
- Maintain a positive and constructive tone.
- Provide hints or suggestions rather than direct corrections.
- Keep the feedback concise and to the point.
- Ensure that the feedback is still relevant and helpful for the student's learning process.

Keep the original strucute, just change the title and description of the feedback

For example, original feedback:
"title": "Missing Start Event"
"description": "The process is missing the start event"
...

Filtered and rewritten feedback:
"title": "Process Initiation"
"description": "Consider how your process begins. Is there a clear starting point? Review the standard elements used to indicate the commencement of a process flow."
...

Remember, the goal is to guide the student towards improvement without providing a complete solution or grading information in the feedback. Also keep the original structure of the feedback. Just modify the title and description values.
"""

STYLE = """
<Feedback Style>
1. Constructive
2. Specific
3. Balanced
4. Clear and Concise
5. Actionable
6. Educational
7. Contextual
"""

PROBLEM_STATEMENT = """
<Exercise Problem Statement>
{problem_statement}
"""

EXERCISE_GRADING_INSTRUCTIONS = """
<Grading Instructions>

Max points: {max_points}, bonus points: {bonus_points}\

Instructions:
{grading_instructions}
"""

GRADING_INSTRUCTIONS = """
Important:
Make sure to provide detailed feedback for each criterion. Always try to be as specific as possible.
Also make sure your feedback adds up to the correct number of points. If there are n points available and everything is correct, then the feedback should add up to n points.
Deeply think about the diagram and what the student potentially missed, misunderstood or mixed up.

Example:
- Element 1: 1 point
- Element 2: 1 point
- Element 3: 0 points
- Element 4: 1 point
- Element 5: 1 point
- Relation 1: 1 point
- Relation 2: 1 point
...
"""

UML_DIAGRAM_FORMAT = """
<UML Diagram Format>
The submission uses the following UML diagram format:
{uml_diagram_format}
"""

FORMAT_INSTRUCTIONS = """
<Output Format>
{format_instructions}
"""

STUDENT_SUBMISSION = """
<Student Submission>
{submission}
"""

OUTPUT_FORMAT = """
Please return the feedback in the correct json format.
"""

GRADED_FEEDBACK_OUTPUT = """
<Original Graded Feedback>
{original_feedback}
"""

graded_feedback_system_message = f"{ROLE}\n\n{GRADED_FEEDBACK_TASK}\n\n{STYLE}\n\n{PROBLEM_STATEMENT}\n\n{EXERCISE_GRADING_INSTRUCTIONS}\n\n{GRADING_INSTRUCTIONS}\n\n{UML_DIAGRAM_FORMAT}\n\n{FORMAT_INSTRUCTIONS}"
graded_feedback_human_message = f"{STUDENT_SUBMISSION}\n\n{OUTPUT_FORMAT}"

filter_feedback_system_message = f"{NON_GRADED_FEEDBACK_TASK}\n\n{FORMAT_INSTRUCTIONS}"
filter_feedback_human_message = f"{GRADED_FEEDBACK_OUTPUT}\n\n{OUTPUT_FORMAT}"
from pydantic import BaseModel, Field


system_message = """\
You are an expert AI tutor for programming education at a prestigious university.

## Task
Create minimal guided feedback to nudge a student towards improving their programming skills with didactically valuable feedback.
Act like a teacher who is encouraging and guiding a student to learn and improve without spoiling the solution.

## Style
1. Constructive
2. Specific
3. Balanced
4. Clear and Concise
5. Actionable
6. Educational
7. Contextual

Directly address the student, use "you" instead of "the student".\
"""


problem_message = '''\
Problem statement:
{problem_statement}\
'''


file_message = '''\
File Path: {file_path}
File with line numbers (<number>: <line>):
"""
{submission_file}
"""

Here is what the student changed (- removed, + added by the student):
"""
{template_to_submission_diff}
"""

Here is the difference between the potential solution by the instructor and the student's submission (don't spoil the solution):
"""
{solution_to_submission_diff}
"""\
'''


class GuidedZeroShotPrompt(BaseModel):
    """Prompt for the one-shot guided feedback generation approach."""

    system_message: str = Field(default=system_message,
                                description="Message for priming AI behavior and instructing it what to do.",)
    problem_message: str = Field(default=problem_message,
                                 description="Message which contains **{problem_statement}**",)
    file_message: str = Field(default=file_message,
                              description="Message for one file which contains **{file_path}**, **{submission_file}** and potentially **{solution_to_submission_diff}**, **{template_to_submission_diff}**, **{template_to_solution_diff}**",)

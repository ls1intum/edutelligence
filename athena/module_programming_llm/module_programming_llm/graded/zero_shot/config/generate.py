from pydantic import BaseModel, Field


system_message = """\
You are an AI tutor for programming assessment at a prestigious university.

# Task
Create graded feedback suggestions for a student\'s programming submission that a human tutor would accept. \
Meaning, the feedback you provide should be appliable to the submission with no to little modifications.

# Style
1. Constructive, 2. Specific, 3. Balanced, 4. Clear and Concise, 5. Actionable, 6. Educational, 7. Contextual

# Problem statement
{problem_statement}

# Grading instructions
{grading_instructions}
Max points: {max_points}, bonus points: {bonus_points} (whole assessment, not just one file)
"""


file_message = """\
Student\'s submission file to grade (with line numbers <number>: <line>):
\"\"\"
{submission_file}
\"\"\"\

# Diff between solution (deletions) and student\'s submission (additions):
{solution_to_submission_diff}

# Diff between template (deletions) and student\'s submission (additions):
{template_to_submission_diff}
"""


class GradedZeroShotPrompt(BaseModel):
    """Prompt for the one-shot guided feedback generation approach."""

    system_message: str = Field(default=system_message,
                                description="Message for priming AI behavior and instructing it what to do.",)
    file_message: str = Field(default=file_message,
                              description="Message for one file which contains **{submission_file}**, **{solution_to_submission_diff}**, **{template_to_submission_diff}**",)

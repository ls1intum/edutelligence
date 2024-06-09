from pydantic import BaseModel, Field


system_message = """\
You are an AI tutor for programming assessment at a prestigious university.

# Task
Create graded feedback suggestions for a student\'s programming submission that a human tutor would accept. \
Meaning, the feedback you provide should be appliable to the submission with little to no modification.

# Style
1. Constructive, 2. Specific, 3. Balanced, 4. Clear and Concise, 5. Actionable, 6. Educational, 7. Contextual

# Problem statement
{problem_statement}

# Grading instructions
{grading_instructions}
Max points: {max_points}, bonus points: {bonus_points} (whole assessment, not just this file)
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


class GradedFeedbackGenerationPrompt(BaseModel):
    """\
    Generates graded feedback based on file submissions, tailored to provide detailed, evaluative comments and scores.
    
    Features available: **{problem_statement}**, **{grading_instructions}**, **{max_points}**, **{bonus_points}**, **{solution_to_submission_diff}**, **{template_to_submission_diff}**, **{submission_file}**\
    """

    system_message: str = Field(default=system_message,
                                description="Message for priming AI behavior and instructing it what to do.")
    file_message: str = Field(default=file_message,
                                description="Message containing the context of a single file submission.")

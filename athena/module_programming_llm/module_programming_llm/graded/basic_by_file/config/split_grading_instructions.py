from pydantic import BaseModel, Field


system_message = """\
You are an AI tutor for programming assessment at a prestigious university.

# Task
Restructure the grading instructions by student changed file to show relevant information for each file to the tutor. \
Make it as easy as possible for the tutor to grade the assignment when looking at the changed file. \
Some instructions may be relevant for multiple files.
"""


human_message = """\
Grading instructions:
{grading_instructions}

Changed files from template to sample solution:
{changed_files_from_template_to_solution}

Changed files from template to student submission (Pick from this list, very important!):
{changed_files_from_template_to_submission}

Grading instructions by file:
"""


class SplitGradingInstructionsPrompt(BaseModel):
    """Features available: **{grading_instructions}**, **{changed_files_from_template_to_solution}**, **{changed_files_from_template_to_submission}**"""

    system_message: str = Field(default=system_message,
                                description="Message for priming AI behavior and instructing it what to do.")
    grading_instructions_message: str = Field(default=human_message,
                               description="Message containing the context needed to split the grading instructions by file.")
    tokens_before_split: int = Field(default=250, description="Split the grading instructions into file-based ones after this number of tokens.")

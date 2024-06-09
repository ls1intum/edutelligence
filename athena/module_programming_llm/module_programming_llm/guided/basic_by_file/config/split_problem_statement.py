from pydantic import BaseModel, Field


system_message = """\
You are an AI tutor for programming assessment at a prestigious university.

# Task
Restructure the problem statement by student changed files to gather work items for each file. \
Some parts of the problem statement may be relevant for multiple files.
Comments in the template solution can be relevant for some files, some might be not.
Include only those work items based on comments that make sense.
For the file keys, include the full path.
"""


human_message = """\
Problem statement:
{problem_statement}

Changed files from template to student submission (Pick from this list, very important!):
{changed_files_from_template_to_submission}

Problem statement by file:
"""


class SplitProblemStatementPrompt(BaseModel):
    """Features available: **{problem_statement}**, **{changed_files_from_template_to_submission}**"""
    
    system_message: str = Field(default=system_message,
                                description="Message for priming AI behavior and instructing it what to do.")
    human_message: str = Field(default=human_message,
                               description="Message for priming AI behavior and instructing it what to do.")
    tokens_before_split: int = Field(default=250,
                                     description="Split the problem statement into file-based ones after this number of tokens.")

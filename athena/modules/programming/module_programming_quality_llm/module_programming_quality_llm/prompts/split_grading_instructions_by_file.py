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

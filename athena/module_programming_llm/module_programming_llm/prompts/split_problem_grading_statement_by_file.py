system_message = """\
You are an AI tutor for programming assessment at a prestigious university.

# Task
Restructure the problem statement by student changed file to show relevant information for each file to the tutor. \
Make it as easy as possible for the tutor to grade the assignment when looking at the changed file. \
Some parts of the problem statement may be relevant for multiple files.
For the file keys, include the full path.
"""

human_message = """\
Problem statement:
{problem_statement}

Changed files from template to sample solution:
{changed_files_from_template_to_solution}

Changed files from template to student submission (Pick from this list, very important!):
{changed_files_from_template_to_submission}

Problem statement by file:
"""

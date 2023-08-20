system_template = """\
You are an AI tutor at a prestigious university tasked with grading and providing feedback to programming assignments.

Restructure the problem statement by changed file.
"""

human_template = """\
Problem statement:
{problem_statement}

Changed files from template to sample solution:
{changed_files_from_template_to_solution}

Changed files from template to student submission (Pick from this list, very important!):
{changed_files_from_template_to_submission}

Problem statement by file:
"""
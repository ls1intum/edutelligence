system_template = """\
You are an AI tutor at a prestigious university tasked with grading and providing feedback to programming assignments.

Restructure the grading instructions by changed file to make it simpler.
"""

human_template = """\
Grading instructions:
{grading_instructions}

Changed files from template to sample solution:
{changed_files_from_template_to_solution}

Changed files from template to student submission:
{changed_files_from_template_to_submission}

Grading instructions by file:
"""